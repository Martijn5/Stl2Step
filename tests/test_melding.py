"""Tests voor de MQTT-melding in watcher.py (geen broker of paho nodig).

Uitvoeren:  pytest tests
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import watcher as w  # noqa: E402


def test_zonder_broker_doet_meld_niets(monkeypatch):
    monkeypatch.setattr(w, "MQTT_HOST", "")
    logs = []
    monkeypatch.setattr(w, "log", logs.append)
    w.meld("klaar", "blok.stl", "3 s")
    assert logs == []


def test_mqtt_fout_laat_watcher_niet_crashen(monkeypatch):
    monkeypatch.setattr(w, "MQTT_HOST", "192.0.2.1")
    monkeypatch.setitem(sys.modules, "paho", None)      # doet alsof paho-mqtt ontbreekt
    logs = []
    monkeypatch.setattr(w, "log", logs.append)
    w.meld("mislukt", "kapot.stl", "lek")
    assert len(logs) == 1
    assert logs[0].startswith("MQTT-melding mislukt")


def test_meld_stuurt_juiste_topic_en_velden(monkeypatch):
    verstuurd = []
    monkeypatch.setattr(w, "stuur", lambda topic, data: verstuurd.append((topic, data)))
    w.meld("klaar", "blok.stl", "3 s")
    topic, data = verstuurd[0]
    assert topic == "stl2step/status"
    assert data["status"] == "klaar"
    assert data["bestand"] == "blok.stl"
    assert "tijd" in data

def test_hangende_broker_blokkeert_watcher_niet(monkeypatch):
    import time
    import types
    paho = types.ModuleType("paho")
    paho.mqtt = types.ModuleType("paho.mqtt")
    paho.mqtt.publish = types.ModuleType("paho.mqtt.publish")
    paho.mqtt.publish.single = lambda *a, **k: time.sleep(60)   # broker die nooit antwoordt
    monkeypatch.setitem(sys.modules, "paho", paho)
    monkeypatch.setitem(sys.modules, "paho.mqtt", paho.mqtt)
    monkeypatch.setitem(sys.modules, "paho.mqtt.publish", paho.mqtt.publish)
    monkeypatch.setattr(w, "MQTT_HOST", "192.0.2.1")
    monkeypatch.setattr(w, "MQTT_TIMEOUT", 1)
    logs = []
    monkeypatch.setattr(w, "log", logs.append)
    t0 = time.time()
    w.meld("klaar", "blok.stl", "3 s")
    assert time.time() - t0 < 5
    assert len(logs) == 1
    assert "geen antwoord" in logs[0]
