from __future__ import annotations
import json, tempfile
from pathlib import Path
from appearance_studio import system_monitor_model as m

def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value) + "\n", encoding="utf-8")

def run():
    assert m.cpu_ticks("cpu 10 20 30 40 5 1 2 3 9 8") == (111,45)
    assert m.cpu_percent((100,50),(200,70)) == 80
    assert m.memory_percent("MemTotal: 1000 kB\nMemAvailable: 650 kB") == 35
    assert m.network_rates((100,200),(600,1200),5) == (100,200)
    assert m.disk_rates((100,200),(600,1200),5) == (100,200)
    assert m.rate_spark([0,10,20,40,80]).endswith("█")
    assert len(m.rate_spark([100]*100)) == 18

    with tempfile.TemporaryDirectory(prefix="appearance-monitor-fixture-") as td:
        base=Path(td); proc=base/"proc"; sys=base/"sys"
        put(sys/"block/nvme0n1/dev","259:0")
        put(sys/"block/loop0/dev","7:0")
        put(proc/"diskstats",
            "259 0 nvme0n1 10 0 100 0 20 0 200 0 0 0 0 0 0 0\n"
            "259 1 nvme0n1p1 10 0 100 0 20 0 200 0 0 0 0 0 0 0\n"
            "7 0 loop0 1 0 999 0 1 0 999 0 0 0 0 0 0 0"
        )
        assert m.disk_counters(proc,sys) == (100*512,200*512)

    diag=m.diagnostic({
        "hostname":"SECRET","iface":"private0","disk_device":"nvme0n1",
        "ip":"1.2.3.4","processes":["personal"],
        "cpu_percent":20,"disk_read_bytes_s":1024,"disk_write_bytes_s":2048,
        "disk_graph":"▁█","network_graph":"▁▂"
    },m.DEFAULTS)
    raw=json.dumps(diag)
    for secret in ("SECRET","private0","nvme0n1","1.2.3.4","personal"):
        assert secret not in raw
    assert diag["metrics"]["disk_read_bytes_s"] == 1024

    menu=m.menu_entries({
        "disk_read_bytes_s":1024,"disk_write_bytes_s":2048,"disk_graph":"▁█",
        "network_graph":"▁▂","rx_bytes_s":100,"tx_bytes_s":200,"batteries":[]
    },m.DEFAULTS,False)
    ids=[entry.id for entry in menu]
    assert len(ids)==len(set(ids))
    assert any("Disk I/O" in entry.label for entry in menu)
    assert any("Network" in entry.label and "▁▂" in entry.label for entry in menu)
    print("SYSTEM_MONITOR_MODEL_PASS")

if __name__=="__main__":
    run()
