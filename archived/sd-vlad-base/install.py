from setup import *

ensure_base_requirements()
parse_args()
setup_logging(args.upgrade)
read_options()
check_python()
if args.reset:
    git_reset()
if args.skip_git:
    log.info('Skipping GIT operations')
check_version()
install_requirements()
log.info("Running setup")
log.debug(f"Args: {vars(args)}")
install_packages()
install_repositories()
install_submodules()
install_extensions()
if errors == 0:
    log.debug(f'Setup complete without errors: {round(time.time())}')
else:
    log.warning(f'Setup complete with errors ({errors})')
    log.warning('See log file for more details: setup.log')
set_environment()
