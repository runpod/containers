"""Instant Cluster smoke path: dev targeting, cluster API plumbing, the
pytorch-cluster checks and the orchestration's teardown guarantees.

No network: the API, SSH and proxy are mocked. The shell snippets are only
syntax-checked with `bash -n`, except the Prometheus target counter, which
runs against a local fake of /api/v1/targets.
"""

import http.server
import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
import unittest
from unittest import mock

from runpod_smoke import (
    api, checks, cluster, cluster_checks, cluster_report, cluster_runner, config,
)


class EnvTargeting(unittest.TestCase):
    def tearDown(self):
        importlib.reload(config)

    def _reload(self, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("RUNPOD_ENV", "RUNPOD_API_ORIGIN", "RUNPOD_PROXY_DOMAIN"):
                if key not in env:
                    os.environ.pop(key, None)
            importlib.reload(config)

    def test_prod_is_the_default(self):
        self._reload()
        self.assertEqual(config.REST_URL, "https://api.runpod.io/v2")
        self.assertEqual(
            config.proxy_url("abc", 8888), "https://abc-8888.proxy.runpod.net",
        )

    def test_dev_switches_api_graphql_and_proxy(self):
        self._reload(RUNPOD_ENV="dev")
        self.assertEqual(config.REST_URL, "https://api.runpod.dev/v2")
        self.assertEqual(config.GRAPHQL_URL, "https://api.runpod.dev/graphql")
        self.assertEqual(
            config.proxy_url("abc", 8889), "https://abc-8889.dev-proxy.runpod.net"
        )

    def test_explicit_hosts_override_the_env_defaults(self):
        self._reload(
            RUNPOD_ENV="dev", RUNPOD_API_ORIGIN="https://api.example/",
            RUNPOD_PROXY_DOMAIN="px.example",
        )
        self.assertEqual(config.REST_URL, "https://api.example/v2")
        self.assertEqual(config.proxy_url("p", 1), "https://p-1.px.example")


class GraphqlErrors(unittest.TestCase):
    def test_errors_in_a_200_are_not_success(self):
        msg = "There are no longer any instances available"
        payload = {"errors": [{"message": msg}]}
        with mock.patch.object(api, "_send", return_value=(200, payload)):
            status, data = api.graphql("q")
        self.assertEqual(status, 400)
        self.assertEqual(api.classify_error(status, data), "UNAVAILABLE")

    def test_insufficient_resources_is_capacity(self):
        """createCluster's reply when no hosts can fit the cluster (dev)."""
        payload = {"errors": [{"message": "Insufficient resources"}]}
        with mock.patch.object(api, "_send", return_value=(200, payload)):
            status, data = api.graphql("q")
        self.assertEqual(api.classify_error(status, data), "UNAVAILABLE")

    def test_server_error_stays_transient(self):
        payload = {"errors": [{"message": "boom"}]}
        with mock.patch.object(api, "_send", return_value=(502, payload)):
            status, data = api.graphql("q")
        self.assertEqual(api.classify_error(status, data), "TRANSIENT")

    def test_success_unwraps_data(self):
        with mock.patch.object(api, "_send", return_value=(200, {"data": {"x": 1}})):
            self.assertEqual(api.graphql("q"), (200, {"x": 1}))


class ClusterApi(unittest.TestCase):
    def test_nodes_sorted_by_rank_and_unplaced_pods_skipped(self):
        nodes = cluster.parse_cluster_nodes([
            {"id": "b", "clusterIdx": 1, "clusterIp": "10.65.0.3"},
            {"id": "c", "clusterIdx": None},
            {"id": "a", "clusterIdx": 0, "clusterIp": "10.65.0.2"},
            {"clusterIdx": 2},
        ])
        self.assertEqual([n.pod_id for n in nodes], ["a", "b"])
        self.assertTrue(nodes[0].is_head)
        self.assertEqual(nodes[1].hostname, "node-1")

    def test_catalog_keeps_cluster_types_cheapest_node_first(self):
        catalog = cluster.parse_cluster_catalog([
            {"id": "NVIDIA A40", "nodeGroupGpuSizes": [10], "clusterPrice": 0.42},
            {"id": "NVIDIA GeForce RTX 4090", "nodeGroupGpuSizes": [2],
             "clusterPrice": 0.888},
            {"id": "NVIDIA L4", "nodeGroupGpuSizes": [1], "clusterPrice": 0.6},
            {"id": "unknown", "nodeGroupGpuSizes": [1], "clusterPrice": 0.1},
            {"id": "NVIDIA H100", "nodeGroupGpuSizes": [], "clusterPrice": 2},
        ])
        self.assertEqual(
            [g.gpu_id for g in catalog],
            ["NVIDIA L4", "NVIDIA GeForce RTX 4090", "NVIDIA A40"],
        )

    def test_gpus_per_node(self):
        self.assertEqual(cluster.pick_gpus_per_node(0, [2, 8]), 2)
        self.assertEqual(cluster.pick_gpus_per_node(8, [2, 8]), 8)
        self.assertIsNone(cluster.pick_gpus_per_node(4, [2, 8]))
        self.assertIsNone(cluster.pick_gpus_per_node(0, []))

    def test_create_input_exposes_grafana_and_points_it_at_the_proxy(self):
        body = cluster.create_cluster_input(
            "runpod/pytorch-cluster:1.4.0-cu1281-torch280-ubuntu2404",
            "NVIDIA L4", "smoketest-1-0001-1", node_count=2, gpus_per_node=1,
        )
        self.assertIn(f"{config.GRAFANA_PORT}/http", body["ports"])
        self.assertIn("8888/http", body["ports"])
        self.assertIn("22/tcp", body["ports"])
        env = {e["key"]: e["value"] for e in body["env"]}
        self.assertEqual(env["RUNPOD_PROXY_BASE"], config.PROXY_DOMAIN)
        self.assertEqual(env["JUPYTER_PASSWORD"], config.JUPYTER_TEST_PASSWORD)
        self.assertEqual(body["minCudaVersion"], "12.8")
        self.assertEqual((body["podCount"], body["type"]), (2, "TRAINING"))
        self.assertTrue(body["startSsh"])

    def _price(self, live, static, gpus=2):
        data = {"gpuTypes": [{"clusterPrice": static,
                              "lowestPrice": {"uninterruptablePrice": live}}]}
        with mock.patch.object(api, "graphql", return_value=(200, data)):
            return cluster.node_price("NVIDIA GeForce RTX 4090", gpus)

    def test_node_price_uses_the_live_cluster_price(self):
        """createCluster's minimum check compares against exactly this."""
        self.assertEqual(self._price(1.48, 0.888), 1.48)

    def test_node_price_falls_back_to_static_price_per_node(self):
        """dev returns no live price for L4; 0.6 x 1 clears its 0.5 floor."""
        self.assertEqual(self._price(None, 0.6, gpus=1), 0.6)

    def test_node_price_override(self):
        with mock.patch.object(config, "CLUSTER_DEPLOY_COST", 9.5), \
             mock.patch.object(api, "graphql") as gql:
            self.assertEqual(cluster.node_price("x", 1), 9.5)
        gql.assert_not_called()

    def test_deploy_cost_is_the_whole_cluster_price(self):
        """The API divides deployCost by podCount before the minimum check."""
        created = (200, {"createCluster": {"id": "c"}})
        with mock.patch.object(cluster, "node_price", return_value=1.48), \
             mock.patch.object(api, "graphql", return_value=created) as gql:
            cid, _, _ = cluster.create_cluster(
                "img", "NVIDIA GeForce RTX 4090", "n", node_count=2, gpus_per_node=2,
            )
        self.assertEqual(cid, "c")
        self.assertEqual(gql.call_args.args[1]["input"]["deployCost"], 2.96)

    def test_create_capacity_error_is_unavailable(self):
        err = (400, {"detail": "There are no longer any instances available"})
        with mock.patch.object(api, "graphql", return_value=err):
            cid, kind, _ = cluster.create_cluster(
                "img", "NVIDIA L4", "n", node_count=2, gpus_per_node=1,
            )
        self.assertIsNone(cid)
        self.assertEqual(kind, "UNAVAILABLE")

    def test_delete_of_a_missing_cluster_is_success(self):
        missing = (400, {"detail": "Cluster not found"})
        with mock.patch.object(api, "graphql", return_value=missing):
            self.assertEqual(cluster.delete_cluster("x"), (True, ""))

    def test_cleanup_all_deletes_registered_clusters(self):
        cluster.register_cluster("c1")
        with mock.patch.object(cluster, "delete_cluster", return_value=(True, "")) as d:
            cluster.cleanup_all_clusters()
        d.assert_called_once_with("c1")
        self.assertNotIn("c1", cluster.ACTIVE_CLUSTER_IDS)


class ProdGuard(unittest.TestCase):
    def setUp(self):
        sys.argv = ["test_images.py"]
        import test_images
        self.ti = test_images
        self.addCleanup(config.GROUP_CLUSTER.clear)
        self.addCleanup(config.GROUP_CLUSTER_NODES.clear)
        self.addCleanup(config.GROUP_CLUSTER_GPUS_PER_NODE.clear)
        self.addCleanup(config.GROUP_TEST_JUPYTER.clear)

    def test_cluster_group_refuses_prod(self):
        with mock.patch.object(config, "RUNPOD_ENV", "prod"), \
             mock.patch.object(config, "ALLOW_PROD_CLUSTERS", False):
            with self.assertRaisesRegex(ValueError, "RUNPOD_ENV=dev"):
                self.ti._apply_cluster_flags("c", {"cluster": True})

    def test_cluster_group_on_dev_implies_jupyter(self):
        with mock.patch.object(config, "RUNPOD_ENV", "dev"):
            self.ti._apply_cluster_flags(
                "c", {"cluster": True, "cluster_nodes": 3, "cluster_gpus_per_node": 2},
            )
        self.assertTrue(config.GROUP_CLUSTER["c"])
        self.assertTrue(config.GROUP_TEST_JUPYTER["c"])
        self.assertEqual(config.GROUP_CLUSTER_NODES["c"], 3)
        self.assertEqual(config.GROUP_CLUSTER_GPUS_PER_NODE["c"], 2)

    def test_bad_node_count_is_rejected(self):
        with mock.patch.object(config, "RUNPOD_ENV", "dev"):
            with self.assertRaises(ValueError):
                self.ti._apply_cluster_flags("c", {"cluster": True, "cluster_nodes": 0})

    def test_cluster_jobs_are_planned_once_without_a_cuda_axis(self):
        config.GROUP_CLUSTER["c"] = True
        manifest = {"c": {"images": ["img"], "cuda_versions": "all"}}
        with mock.patch.object(config, "CLOUD_TYPES", ["SECURE", "COMMUNITY"]):
            first = self.ti._build_jobs(manifest, {"c": ["L4"]}, None, [], "SECURE")
            second = self.ti._build_jobs(manifest, {"c": ["L4"]}, None, [], "COMMUNITY")
        self.assertEqual(first, [("img", "c", ["L4"], "", "SECURE")])
        self.assertEqual(second, [])


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class ShellSnippets(unittest.TestCase):
    def _bash_n(self, script):
        r = subprocess.run(["bash", "-n", "-c", script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_snippets_parse(self):
        self._bash_n(cluster_checks.node_identity_command(0))
        self._bash_n(cluster_checks.head_monitoring_command(2, 30))
        self._bash_n(cluster_checks.head_monitoring_command(2, 30, require_dcgm=False))
        self._bash_n(cluster_checks.worker_monitoring_command(30))

    def test_identity_names_the_expected_host(self):
        self.assertIn("node-3", cluster_checks.node_identity_command(3))

    def test_head_waits_for_every_program_and_job(self):
        cmd = cluster_checks.head_monitoring_command(4, 30)
        for program in cluster_checks.HEAD_PROGRAMS:
            self.assertIn(program, cmd)
        self.assertTrue(cmd.rstrip().endswith("4 30 node dcgm"))
        no_dcgm = cluster_checks.head_monitoring_command(4, 30, require_dcgm=False)
        self.assertNotIn("dcgm-exporter", no_dcgm)
        self.assertTrue(no_dcgm.rstrip().endswith("4 30 node"))

    def test_worker_rejects_head_only_services(self):
        cmd = cluster_checks.worker_monitoring_command(30)
        for program in cluster_checks.HEAD_ONLY_PROGRAMS:
            self.assertIn(program, cmd)


class _Targets(http.server.BaseHTTPRequestHandler):
    payload: dict = {}

    def do_GET(self):  # noqa: N802
        body = json.dumps(self.payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class PrometheusTargetCounter(unittest.TestCase):
    """Runs the embedded program for real against a fake targets API."""

    def _run(self, targets, want):
        _Targets.payload = {"data": {"activeTargets": targets}}
        try:
            server = http.server.HTTPServer(("127.0.0.1", 9090), _Targets)
        except OSError:
            self.skipTest("port 9090 busy")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            return subprocess.run(
                [sys.executable, "-c", cluster_checks._TARGETS_PROGRAM,
                 str(want), "0", "node", "dcgm"],
                capture_output=True, text=True, timeout=30,
            )
        finally:
            server.shutdown()
            server.server_close()

    @staticmethod
    def _t(job, inst, health="up"):
        return {"labels": {"job": job, "instance": inst}, "health": health}

    def _both(self, job, port, node1_health="up"):
        """One job's target on node-0 and node-1."""
        return [self._t(job, f"node-0:{port}"),
                self._t(job, f"node-1:{port}", node1_health)]

    def test_every_node_scraped_passes(self):
        r = self._run(self._both("node", 9100) + self._both("dcgm", 9400), 2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("targets OK", r.stdout)

    def test_head_scraping_only_itself_fails(self):
        """The /etc/hosts fallback: post_start.sh found no peers."""
        r = self._run(
            [self._t("node", "node-0:9100"), self._t("dcgm", "node-0:9400")], 2,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("node 1/2", r.stdout)

    def test_down_worker_fails(self):
        r = self._run(self._both("node", 9100, "down") + self._both("dcgm", 9400), 2)
        self.assertEqual(r.returncode, 1)


class GrafanaProxyCheck(unittest.TestCase):
    HEALTH = (200, '{"database": "ok", "version": "11"}')
    USER = (200, '{"login": "runpod"}')
    QUERY = (200, '{"status": "success", "data": {"result": [{"metric": {}}]}}')

    def _check(self, responses):
        with mock.patch.object(cluster_checks, "_get", side_effect=responses) as get, \
             mock.patch.object(cluster_checks.time, "sleep"):
            ok, out = cluster_checks.run_grafana_proxy_check("pod1")
        return ok, out, [c.args[0] for c in get.call_args_list]

    def test_healthy_protected_and_querying_passes(self):
        ok, out, urls = self._check([self.HEALTH, self.USER, (401, ""), self.QUERY])
        self.assertTrue(ok, out)
        base = config.proxy_url("pod1", config.GRAFANA_PORT)
        self.assertTrue(urls[0].startswith(base))
        self.assertNotIn(config.JUPYTER_TEST_PASSWORD, out.replace("<redacted>", ""))

    def test_open_grafana_fails(self):
        ok, out, _ = self._check([self.HEALTH, self.USER, self.USER])
        self.assertFalse(ok)
        self.assertIn("not protected", out)

    def test_token_not_accepted_fails(self):
        ok, out, _ = self._check([self.HEALTH, (401, '{"message":"Unauthorized"}')])
        self.assertFalse(ok)
        self.assertIn("shared token", out)

    def test_empty_datasource_fails(self):
        empty = (200, '{"status": "success", "data": {"result": []}}')
        ok, out, _ = self._check([self.HEALTH, self.USER, (401, ""), empty])
        self.assertFalse(ok)
        self.assertIn("Prometheus datasource", out)

    def test_never_healthy_times_out(self):
        with mock.patch.object(config, "GRAFANA_PROXY_TIMEOUT", 0):
            ok, out, _ = self._check([(502, "bad gateway")])
        self.assertFalse(ok)
        self.assertIn("/api/health not ok", out)


class Orchestration(unittest.TestCase):
    NODES = [cluster.ClusterNode("p0", 0), cluster.ClusterNode("p1", 1)]

    def _patch(self, **overrides):
        defaults = dict(
            _log_attempt_header=mock.Mock(return_value=(False, "NVIDIA L4")),
            cluster_gpu_sizes=mock.Mock(return_value=[1]),
            create_cluster=mock.Mock(return_value=("cl1", "", "")),
            register_cluster=mock.Mock(),
            cleanup_cluster=mock.Mock(),
            wait_for_nodes=mock.Mock(return_value=(self.NODES, "")),
            wait_for_running=mock.Mock(
                side_effect=lambda pid, timeout=None: (
                    "RUNNING", "ok", mock.Mock(name=pid))
            ),
            pod_state=mock.Mock(return_value={"cuda_version": "12.8"}),
            run_simple_check=mock.Mock(return_value=(True, "")),
            run_grafana_proxy_check=mock.Mock(return_value=(True, "grafana check OK")),
            _run_cuda_step=mock.Mock(return_value=None),
            _run_jupyter_steps=mock.Mock(return_value=None),
            _run_hygiene_steps=mock.Mock(return_value=None),
            _run_log_scan_step=mock.Mock(return_value=None),
            dump_pod_logs=mock.Mock(),
        )
        defaults.update(overrides)
        patches = [mock.patch.object(cluster_runner, k, v) for k, v in defaults.items()]
        patches.append(mock.patch.object(config, "DWELL_SEC", 0))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return defaults

    def test_happy_path_checks_every_node_and_tears_down(self):
        m = self._patch()
        self.assertEqual(
            cluster_runner.test_cluster_pair("img", "L4", "g"), ("PASS", ""),
        )
        self.assertEqual(m["wait_for_running"].call_count, 2)
        # One shared boot deadline, so neither node gets more than the whole.
        for call in m["wait_for_running"].call_args_list:
            self.assertLessEqual(call.kwargs["timeout"], config.CLUSTER_BOOT_TIMEOUT)
        self.assertEqual(m["_run_jupyter_steps"].call_count, 2)
        m["run_grafana_proxy_check"].assert_called_once_with("p0")
        m["_run_hygiene_steps"].assert_called_once()
        m["cleanup_cluster"].assert_called_once_with("cl1")

    def test_grafana_failure_fails_and_still_tears_down(self):
        m = self._patch(run_grafana_proxy_check=mock.Mock(return_value=(False, "FAIL")))
        status, detail = cluster_runner.test_cluster_pair("img", "L4", "g")
        self.assertEqual(status, "FAIL")
        self.assertIn("node-0", detail)
        self.assertIn("Grafana", detail)
        m["cleanup_cluster"].assert_called_once_with("cl1")

    def test_cuda_failure_skips_jupyter_on_that_node(self):
        m = self._patch(_run_cuda_step=mock.Mock(return_value=("FAIL", "CUDA broken")))
        self.assertEqual(
            cluster_runner.test_cluster_pair("img", "L4", "g"),
            ("FAIL", "node-0: CUDA broken"),
        )
        m["_run_jupyter_steps"].assert_not_called()

    def test_members_never_appearing_is_stuck(self):
        m = self._patch(wait_for_nodes=mock.Mock(return_value=(None, "only 1 of 2")))
        self.assertEqual(
            cluster_runner.test_cluster_pair("img", "L4", "g"), ("STUCK", ""),
        )
        m["cleanup_cluster"].assert_called_once_with("cl1")

    def test_gpu_not_offered_for_clusters_is_unavailable(self):
        m = self._patch(cluster_gpu_sizes=mock.Mock(return_value=[]))
        self.assertEqual(
            cluster_runner.test_cluster_pair("img", "L4", "g"), ("UNAVAILABLE", ""),
        )
        m["create_cluster"].assert_not_called()

    def test_exception_mid_run_still_tears_down(self):
        m = self._patch(_run_cuda_step=mock.Mock(side_effect=RuntimeError("x")))
        with self.assertRaises(RuntimeError):
            cluster_runner.test_cluster_pair("img", "L4", "g")
        m["cleanup_cluster"].assert_called_once_with("cl1")


class Reaper(unittest.TestCase):
    def test_only_old_smoketest_clusters(self):
        sys.argv = ["reap_clusters.py"]
        import reap_clusters
        now = 1_800_000_000
        stale = reap_clusters.stale_clusters([
            {"id": "a", "name": f"smoketest-{now - 7200}-0001-1"},
            {"id": "b", "name": f"smoketest-{now - 60}-0001-1"},
            {"id": "c", "name": "murat-cluster"},
            {"id": "d", "name": "my smoketest-1700000000-x"},
        ], now, 5400)
        self.assertEqual([s[0] for s in stale], ["a"])


if __name__ == "__main__":
    unittest.main()


class ClusterTypes(unittest.TestCase):
    """Dev refused TRAINING clusters for a GPU it deploys fine as SLURM."""

    def setUp(self):
        self._saved = dict(config.GROUP_CLUSTER_TYPES)
        config.GROUP_CLUSTER_TYPES.clear()

    def tearDown(self):
        config.GROUP_CLUSTER_TYPES.clear()
        config.GROUP_CLUSTER_TYPES.update(self._saved)

    def test_input_carries_the_type(self):
        body = cluster.create_cluster_input(
            "img", "NVIDIA L4", "n", node_count=2, gpus_per_node=1,
            cluster_type="SLURM",
        )
        self.assertEqual(body["type"], "SLURM")

    def test_default_is_standard_then_slurm(self):
        with mock.patch.object(config, "CLUSTER_TYPES_OVERRIDE", ""):
            self.assertEqual(cluster.cluster_types_for("g"), ("TRAINING", "SLURM"))

    def test_env_override_wins_over_the_manifest(self):
        config.GROUP_CLUSTER_TYPES["g"] = ("TRAINING",)
        with mock.patch.object(config, "CLUSTER_TYPES_OVERRIDE", "slurm, ray"):
            self.assertEqual(cluster.cluster_types_for("g"), ("SLURM", "RAY"))

    def test_parse_rejects_unknown_and_empty(self):
        with self.assertRaises(ValueError):
            cluster.parse_cluster_types(["TRAINING", "STANDARD"], "x")
        with self.assertRaises(ValueError):
            cluster.parse_cluster_types([], "x")
        self.assertEqual(
            cluster.parse_cluster_types(["slurm", "SLURM", "training"], "x"),
            ("SLURM", "TRAINING"),
        )

    def _create(self, results):
        calls = []

        def fake(*_a, cluster_type, **_k):
            calls.append(cluster_type)
            return results[cluster_type]

        with mock.patch.object(cluster_runner, "create_cluster", side_effect=fake), \
             mock.patch.object(config, "CLUSTER_TYPES_OVERRIDE", ""), \
             mock.patch.object(config, "CREATE_RETRIES", 1):
            out = cluster_runner._create_cluster_with_retries(
                "img", "NVIDIA L4", "g", 2, 1,
            )
        return out, calls

    def test_refused_standard_falls_back_to_slurm(self):
        out, calls = self._create({
            "TRAINING": (None, "UNAVAILABLE", "Insufficient resources"),
            "SLURM": ("cl-slurm", "", ""),
        })
        self.assertEqual(out, ("cl-slurm", "", ""))
        self.assertEqual(calls, ["TRAINING", "SLURM"])

    def test_standard_success_never_tries_slurm(self):
        out, calls = self._create({"TRAINING": ("cl1", "", ""), "SLURM": ("x", "", "")})
        self.assertEqual(out[0], "cl1")
        self.assertEqual(calls, ["TRAINING"])

    def test_all_refused_reports_the_last_verdict(self):
        out, _ = self._create({
            "TRAINING": (None, "FATAL", "some bug"),
            "SLURM": (None, "UNAVAILABLE", "Insufficient resources"),
        })
        self.assertEqual(out[:2], (None, "UNAVAILABLE"))


class ExcludedDataCenter(unittest.TestCase):
    """createCluster still places on a stopped dev host (K3S-POC)."""

    NODES = [cluster.ClusterNode("p0", 0), cluster.ClusterNode("p1", 1)]

    def _dc(self, dcs, excluded="K3S-POC"):
        with mock.patch.object(config, "CLUSTER_EXCLUDE_DATA_CENTERS", excluded), \
             mock.patch.object(cluster_runner, "pod_state",
                               side_effect=lambda pid: {"data_center": dcs[pid]}):
            return cluster_runner._excluded_data_center(self.NODES)

    def test_dead_host_is_caught(self):
        self.assertEqual(self._dc({"p0": "SPACE-1", "p1": "K3S-POC"}), "K3S-POC")

    def test_healthy_placement_passes(self):
        self.assertEqual(self._dc({"p0": "SPACE-1", "p1": "SPACE-1"}), "")

    def test_empty_list_disables_the_check(self):
        self.assertEqual(self._dc({"p0": "K3S-POC", "p1": "K3S-POC"}, excluded=""), "")


class SlurmPlatformLogNoise(unittest.TestCase):
    """A SLURM cluster's own daemons log `error:` on first boot; seen on dev."""

    LINES = [
        "Starting Jupyter Lab...",
        "slurmctld: error:  mpi/pmix_v5: init: (null) [0]: mpi_pmix.c:193: "
        "pmi/pmix: can not load PMIx library",
        "slurmd: error: MPI: Cannot create context for mpi/pmix",
        "[cluster] post-start complete",
    ]

    def _scan(self, lines):
        with mock.patch.object(checks, "fetch_pod_logs_api", return_value=lines), \
             mock.patch.object(api, "load_api_key", return_value="k"):
            return checks.scan_pod_logs_for_errors("p")

    def test_slurm_daemon_lines_are_ignored(self):
        ok, report = self._scan(self.LINES)
        self.assertTrue(ok, report)
        self.assertIn("2 platform line(s) ignored", report)

    def test_image_errors_are_still_caught(self):
        ok, report = self._scan(self.LINES + ["grafana: ERROR failed to bind :3300"])
        self.assertFalse(ok)
        self.assertIn("grafana", report)
        self.assertNotIn("pmix", report)


class ReportCard(unittest.TestCase):
    """The per-cluster table printed after each attempt and under SUMMARY."""

    NODES = Orchestration.NODES
    _patch = Orchestration._patch

    def _last(self):
        return cluster_report.REPORTS[-1]

    def setUp(self):
        saved = list(cluster_report.REPORTS)
        self.addCleanup(cluster_report.REPORTS.__setitem__, slice(None), saved)

    def _rows(self):
        return {row[0]: row[1:] for row in self._last()._table()[1]}

    def test_pass_fills_every_node(self):
        self._patch()
        cluster_runner.test_cluster_pair("img", "L4", "g")
        rows = self._rows()
        self.assertEqual(self._last().verdict, "PASS")
        self.assertEqual(rows["hostname / rank"], ["ok", "ok"])
        self.assertEqual(rows["Grafana via proxy :8889"], ["ok", "-"])
        self.assertEqual(rows["log scan"][0], "ok")

    def test_failure_shows_where_it_stopped(self):
        self._patch(run_grafana_proxy_check=mock.Mock(return_value=(False, "x")))
        cluster_runner.test_cluster_pair("img", "L4", "g")
        rows = self._rows()
        self.assertEqual(rows["Grafana via proxy :8889"], ["FAIL", "-"])
        self.assertEqual(rows["log scan"], ["not run", "not run"])
        text = "\n".join(self._last().render_text())
        self.assertIn("stopped at: node-0: Grafana", text)

    def test_no_cluster_no_card(self):
        before = len(cluster_report.REPORTS)
        self._patch(cluster_gpu_sizes=mock.Mock(return_value=[]))
        cluster_runner.test_cluster_pair("img", "L4", "g")
        self.assertEqual(len(cluster_report.REPORTS), before)
