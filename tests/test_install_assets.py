from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_web_service_file_exists():
    assert (REPO_ROOT / "cursed-controls-web.service").exists()


def test_web_service_runs_serve_entrypoint():
    service = (REPO_ROOT / "cursed-controls-web.service").read_text()
    assert "After=network.target bluetooth.target" in service
    assert "Wants=bluetooth.target" in service
    assert "ExecStartPre=/bin/bash" in service
    assert "cursed_controls.cli serve" in service
    assert "Restart=on-failure" in service
    assert "KillMode=mixed" in service


def test_install_script_seeds_tv_remote_mapping():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "example_tv_remote.yaml" in install
    assert "mapping.yaml" in install


def test_install_script_does_not_inline_overwrite_init_script():
    install = (REPO_ROOT / "install.sh").read_text()
    assert 'cat > "$CC_DIR/init-raspbian.sh"' not in install


def test_raw_gadget_submodule_uses_https():
    gitmodules = (REPO_ROOT / ".gitmodules").read_text()
    assert "https://github.com/CasperVM/360-w-raw-gadget.git" in gitmodules
    assert "git@github.com:CasperVM/360-w-raw-gadget.git" not in gitmodules


def test_init_script_falls_back_to_user_home_for_raw_gadget():
    init_script = (REPO_ROOT / "init-raspbian.sh").read_text()
    assert "__RAW_GADGET_DIR__" not in init_script
    assert 'dirname -- "$0"' in init_script
    assert 'RAW_GADGET_DIR="${RAW_GADGET_DIR:-' in init_script


def test_setup_doc_mentions_web_service():
    setup = (REPO_ROOT / "SetupRaspbian.md").read_text()
    assert "cursed-controls-web.service" in setup


def test_docs_demo_files_exist():
    for rel in ("docs/index.html", "docs/style.css", "docs/app.js"):
        assert (REPO_ROOT / rel).exists()


def test_docs_demo_is_static():
    html = (REPO_ROOT / "docs/index.html").read_text()
    js = (REPO_ROOT / "docs/app.js").read_text()
    assert "Demo only" in html
    assert "/api/" not in js
    assert "new WebSocket" not in js


def test_readme_mentions_demo():
    readme = (REPO_ROOT / "README.md").read_text()
    assert "demo" in readme.lower()


def test_install_script_supports_headless_fast_boot_flag():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "--headless-fast-boot" in install


def test_install_script_repairs_host_mode_dwc2_overlay():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "dtoverlay=dwc2,dr_mode=host" in install
    assert "dtoverlay=dwc2" in install
    assert "sed -i" in install


def test_install_script_lists_headless_fast_boot_settings():
    install = (REPO_ROOT / "install.sh").read_text()
    for line in (
        "hdmi_blanking=1",
        "hdmi_ignore_hotplug=1",
        "camera_auto_detect=0",
        "display_auto_detect=0",
        "dtparam=audio=off",
        "gpu_mem=16",
        "dtparam=act_led_trigger=none",
        "dtparam=act_led_activelow=on",
    ):
        assert line in install


def test_readme_mentions_headless_fast_boot():
    readme = (REPO_ROOT / "README.md").read_text()
    assert "--headless-fast-boot" in readme


def test_setup_doc_mentions_headless_fast_boot():
    setup = (REPO_ROOT / "SetupRaspbian.md").read_text()
    assert "--headless-fast-boot" in setup


def test_install_script_installs_uv():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "https://astral.sh/uv/install.sh" in install


def test_install_script_uses_uv_for_python_env():
    install = (REPO_ROOT / "install.sh").read_text()
    assert " venv " in install
    assert " sync " in install or " pip install " in install
    assert "UV_BIN" in install


def test_install_script_uses_piwheels_on_armv6_with_uv():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "piwheels.org/simple" in install
    assert 'if [ "$ARCH" = "armv6l" ]' in install
    assert '"$UV_BIN" pip install \\' in install
    assert '--python "$CC_DIR/.venv/bin/python" \\' in install
    assert '--index-url https://www.piwheels.org/simple' in install
    assert "evdev==1.9.2" in install
    assert "PyYAML==6.0.3" in install
    assert "pydantic-core==2.41.4" in install


def test_install_script_installs_python_dev_headers():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "python3-dev" in install


def test_base_dependencies_do_not_require_uvicorn_standard_extras():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert 'uvicorn[standard]' not in pyproject
    assert 'uvicorn>=' in pyproject


def test_uv_sources_pin_armv6_packages_to_piwheels():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert '[[tool.uv.index]]' in pyproject
    assert 'name = "piwheels"' in pyproject
    assert 'url = "https://www.piwheels.org/simple"' in pyproject
    assert 'explicit = true' in pyproject
    assert 'evdev = { index = "piwheels", marker = "platform_machine == \'armv6l\'" }' in pyproject
    assert 'pyyaml = { index = "piwheels", marker = "platform_machine == \'armv6l\'" }' in pyproject
    assert 'pydantic-core = { index = "piwheels", marker = "platform_machine == \'armv6l\'" }' in pyproject


def test_lockfile_pins_armv6_wheel_backed_pydantic_core():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    lock = (REPO_ROOT / "uv.lock").read_text()
    assert 'pydantic==2.12.3' in pyproject
    assert 'name = "pydantic-core"' in lock
    assert 'version = "2.41.4"' in lock


def test_install_script_uses_repo_python_version_for_uv():
    install = (REPO_ROOT / "install.sh").read_text()
    assert ".python-version" in install
    assert "PYTHON_REQUEST" in install
    assert '"$UV_BIN" venv --python "$PYTHON_REQUEST"' in install
    assert '"$UV_BIN" sync \\' in install
    assert '--directory "$CC_DIR" \\' in install
    assert '--python "$PYTHON_REQUEST" \\' in install


def test_install_script_syncs_submodule_urls():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "git submodule sync --recursive" in install
    assert "git submodule update --init --recursive" in install


def test_install_script_builds_xwiimote():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "https://github.com/xwiimote/xwiimote.git" in install
    assert "./autogen.sh" in install
    assert "make -j\"$BUILD_JOBS\"" in install
    assert "sudo make install" in install


def test_install_script_patches_xwiimote_for_time64_input_headers():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "input_event_sec" in install
    assert "input_event_usec" in install
    assert "copy_input_event_time" in install


def test_install_script_tolerates_xwiimote_build_failure():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "libxwiimote not available" in install
    assert "warn " in install


def test_repo_python_version_matches_current_pi_os():
    python_version = (REPO_ROOT / ".python-version").read_text().strip()
    assert python_version == "3.13"
