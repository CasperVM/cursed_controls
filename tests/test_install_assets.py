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


def test_init_script_falls_back_to_user_home_for_raw_gadget():
    init_script = (REPO_ROOT / "init-raspbian.sh").read_text()
    assert "__RAW_GADGET_DIR__" not in init_script
    assert 'dirname -- "$0"' in init_script
    assert 'RAW_GADGET_DIR="${RAW_GADGET_DIR:-' in init_script


def test_setup_doc_mentions_web_service():
    setup = (REPO_ROOT / "SetupRaspbian.md").read_text()
    assert "cursed-controls-web.service" in setup


def test_install_script_supports_headless_fast_boot_flag():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "--headless-fast-boot" in install


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


def test_install_script_installs_python_dev_headers():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "python3-dev" in install


def test_install_script_uses_repo_python_version_for_uv():
    install = (REPO_ROOT / "install.sh").read_text()
    assert ".python-version" in install
    assert "PYTHON_REQUEST" in install
    assert '"$UV_BIN" venv --python "$PYTHON_REQUEST"' in install
    assert '"$UV_BIN" sync --directory "$CC_DIR" --python "$PYTHON_REQUEST"' in install


def test_install_script_builds_xwiimote():
    install = (REPO_ROOT / "install.sh").read_text()
    assert "https://github.com/xwiimote/xwiimote.git" in install
    assert "./autogen.sh" in install
    assert "make -j\"$BUILD_JOBS\"" in install
    assert "sudo make install" in install


def test_repo_python_version_matches_current_pi_os():
    python_version = (REPO_ROOT / ".python-version").read_text().strip()
    assert python_version == "3.13"
