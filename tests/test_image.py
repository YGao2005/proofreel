import hashlib
import urllib.request

import pytest

from proofreel import Problem, image, qemu, vm


def test_sha512_lookup_reads_a_sums_file():
    sums = "aa  other.qcow2\nbb *debian-13-generic-arm64.qcow2\n"
    assert image.expected(sums, "debian-13-generic-arm64.qcow2") == "bb"
    with pytest.raises(Problem, match="does not list"):
        image.expected(sums, "missing.qcow2")


def serve(monkeypatch, files):
    monkeypatch.setattr(image, "fetch", lambda name, target: target.write_bytes(files[name]))


def test_download_keeps_a_file_that_matches(home, monkeypatch):
    data = b"disk"
    serve(monkeypatch, {"SHA512SUMS": f"{hashlib.sha512(data).hexdigest()}  {image.FILE}\n".encode(), image.FILE: data})
    assert image.download().read_bytes() == data


def test_download_fetches_again_when_the_cached_file_is_stale(home, monkeypatch):
    data = b"new"
    serve(monkeypatch, {"SHA512SUMS": f"{hashlib.sha512(data).hexdigest()}  {image.FILE}\n".encode(), image.FILE: data})
    (home / "images").mkdir(parents=True)
    (home / "images" / image.FILE).write_bytes(b"old")
    assert image.download().read_bytes() == data


def test_download_refuses_a_file_with_a_wrong_sha(home, monkeypatch):
    serve(monkeypatch, {"SHA512SUMS": f"{'0' * 128}  {image.FILE}\n".encode(), image.FILE: b"bad"})
    with pytest.raises(Problem, match="does not match its SHA-512"):
        image.download()
    assert not (home / "images" / image.FILE).exists()


def test_a_missing_qemu_says_how_to_install_it(monkeypatch):
    monkeypatch.setattr(qemu.shutil, "which", lambda tool: None)
    with pytest.raises(Problem, match="qemu-system-aarch64 and qemu-img.*brew install qemu.*apt install"):
        qemu.need_qemu()


def test_make_refuses_an_existing_state_before_it_downloads(home, monkeypatch):
    vm.write_state("linux", parent="x", user="u", password="p", warm=False, backend="qemu", os="linux")
    monkeypatch.setattr(image, "download", lambda: pytest.fail("downloaded"))
    with pytest.raises(Problem, match="proofreel vm drop linux"):
        image.make()


def test_make_checks_the_name_and_the_tools_first(home, monkeypatch):
    with pytest.raises(Problem, match="State name"):
        image.make("bad name")
    monkeypatch.setattr(qemu.shutil, "which", lambda tool: None)
    monkeypatch.setattr(image, "download", lambda: pytest.fail("downloaded"))
    with pytest.raises(Problem, match="brew install qemu"):
        image.make()


def test_the_seed_server_gives_the_cloud_init_files():
    seed = image.Seed()
    try:
        port = seed.server_address[1]
        user_data = urllib.request.urlopen(f"http://127.0.0.1:{port}/user-data").read()
        assert b"#cloud-config" in user_data and b"tester" in user_data
        assert f"serial=ds=nocloud;s=http://10.0.2.2:{port}/" in seed.smbios[1]
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/../debian-desktop.sh")
    finally:
        seed.shutdown()
