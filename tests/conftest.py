import os
import pytest

os.environ["BACKBONE_NO_SECRETS_FILE"] = "1"  # hermetic: no test may read the router's local secrets file or send a real message


@pytest.fixture(autouse=True)
def isolated_runtime_state(tmp_path, monkeypatch):
    # Fake credentials must never cool down real aliases or consume their quota.
    from backbone import keys, otel, hook
    monkeypatch.setattr(keys, 'STATE_FILE', str(tmp_path / 'key-state.json'))
    monkeypatch.setattr(otel, '_TRACER', False)
    monkeypatch.setattr(hook, 'INDEX_PATH', str(tmp_path / 'library-index.jsonl'))


@pytest.fixture(autouse=True)
def no_external_test_network(monkeypatch):
    import socket
    connect = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            pytest.fail('external network forbidden in unit tests')
        return connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', local_only)
