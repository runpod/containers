# k3s-node: notes for agents

This repository is public, and the published image contains `k3s-node.sh` as it is. Anyone can
read every comment and log message in these files.

## Comments and log messages

Comments explain what the code does and why. They contain public information only.

Do not put these in comments, log messages, or this README:

- Ticket or issue IDs (for example Linear `E-…` or `CON-…` IDs).
- Names or paths of internal repositories, services, or infrastructure (for example the control
  plane repository, AWS stacks, tasks, or DNS setups).
- Internal IP addresses, subnets, or example addresses from real networks. If the code must
  contain an address, the comment does not repeat or explain it.
- Host operating system versions, fleet details, hostnames, or account names.
- Secrets, tokens, or key material, also as examples.

Keep that context in the ticket or in a private repository. Commit messages, branch names, and
pull requests in this repository are public too.

Before you commit a change in this directory, read every comment and log message in the diff
against this list.
