import os
import sys
import re
import requests
from datetime import datetime, timezone
from supabase import create_client, Client

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==============================================================================
# 1. ตั้งค่าการเชื่อมต่อ Supabase
# ==============================================================================
SUPABASE_URL = "https://ycchozbszqxxmvxwdlag.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("❌ ไม่พบ SUPABASE_KEY ใน Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ผัง 10 สถานี เกณฑ์เตือนภัย (ลบ.ม./วิ) และค่าสำรอง (Fallback)
STATIONS_CONFIG = {
    # ลุ่มน้ำเจ้าพระยา (HII TIWRM)
    "C2": {"name": "แม่น้ำเจ้าพระยา C.2 (นครสวรรค์)", "basin": "chao_phraya", "warning": 2000, "critical": 2800, "default": 1904},
    "C13": {"name": "เขื่อนเจ้าพระยา C.13 (ชัยนาท)", "basin": "chao_phraya", "warning": 2000, "critical": 2700, "default": 2200},
    "pasak": {"name": "เขื่อนป่าสักชลสิทธิ์", "basin": "chao_phraya", "warning": 400, "critical": 600, "default": 115},
    "rama6": {"name": "เขื่อนพระรามหก (แม่น้ำป่าสัก)", "basin": "chao_phraya", "warning": 500, "critical": 700, "default": 410},
    "C29A": {"name": "สถานี C.29A บางไทร (อยุธยา)", "basin": "chao_phraya", "warning": 2500, "critical": 3000, "default": 2250},

    # ลุ่มน้ำแม่กลอง (HII EGAT / MK Monitor)
    "srinagarind": {"name": "เขื่อนศรีนครินทร์ (กาญจนบุรี)", "basin": "mae_klong", "warning": 400, "critical": 600, "default": 180},
    "vajiralongkorn": {"name": "เขื่อนวชิราลงกรณ (กาญจนบุรี)", "basin": "mae_klong", "warning": 300, "critical": 500, "default": 120},
    "maeklong_dam": {"name": "เขื่อนแม่กลอง (K.10 ท่าม่วง)", "basin": "mae_klong", "warning": 1200, "critical": 2000, "default": 1000},

    # ลุ่มน้ำบางปะกง (HII RID Dam)
    "khundan": {"name": "เขื่อนขุนด่านปราการชล", "basin": "bang_pakong", "warning": 100, "critical": 200, "default": 50},
    "bangpakong_gate": {"name": "ปตร. แม่น้ำบางปะกง", "basin": "bang_pakong", "warning": 400, "critical": 600, "default": 310}
}

def fetch_html_auto_encoding(url, timeout=15):
    """ฟังก์ชันกลางสำหรับดึงหน้าเว็บและตรวจจับภาษาไทยให้อ่านออก 100%"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://tiwrm.hii.or.th/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            for enc in ["utf-8", "tis-620", "cp874"]:
                try:
                    text = resp.content.decode(enc)
                    if any(k in text for k in ["เขื่อน", "ระดับ", "น้ำ", "สถานี", "ม."]):
                        return text
                except Exception:
                    pass
            return resp.content.decode("tis-620", errors="ignore")
    except Exception as e:
        print(f"⚠️ ดึง URL {url} ขัดข้อง: {e}")
    return ""

# ==============================================================================
# 2. ดึงสถานีลุ่มน้ำเจ้าพระยา (C.2, C.13, C.29A, พระรามหก)
# ==============================================================================
def scrape_hii_chaopraya():
    url = "https://tiwrm.hii.or.th/DATA/REPORT/php/chart/chaopraya/2013/chaopraya.php"
    html = fetch_html_auto_encoding(url)
    hii_results = {}

    if html:
        print("📡 [HII TIWRM Flow] เชื่อมต่อสำเร็จ")
        station_rules = {
            "C2": (r"C\.?\s*2\b.*?([0-9]{3,4}(?:,[0-9]{3})*)", 300),
            "C13": (r"C\.?\s*13\b.*?([0-9]{2,4}(?:,[0-9]{3})*)", 100),
            "C29A": (r"C\.?\s*29A?\b.*?([0-9]{3,4}(?:,[0-9]{3})*)", 500),
            "rama6": (r"(?:พระรามหก|S\.?\s*26).*?([0-9]{2,4}(?:,[0-9]{3})*)", 10),
            "pasak": (r"(?:ป่าสัก|pasak).*?([0-9]{1,4}(?:,[0-9]{3})*)", 5)
        }

        for sid, (pattern, min_valid) in station_rules.items():
            matches = re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)
            for m in matches:
                val = float(m.group(1).replace(",", ""))
                if val >= min_valid:
                    hii_results[sid] = round(val)
                    print(f"   ✓ [HII Flow Match] {sid}: {hii_results[sid]} ลบ.ม./วิ")
                    break

    return hii_results

# ==============================================================================
# 3. ดึงเขื่อนขนาดใหญ่ (กฟผ. และ ชลประทาน)
# ==============================================================================
def fetch_all_dams():
    dam_results = {}

    # 3.1 เขื่อน กฟผ. (ศรีนครินทร์, วชิราลงกรณ)
    egat_html = fetch_html_auto_encoding("https://tiwrm.hii.or.th/DATA/REPORT/php/egat_dam.php")
    if egat_html:
        print("📡 [HII EGAT Dams] เชื่อมต่อสำเร็จ")
        egat_targets = {"ศรีนครินทร์": "srinagarind", "วชิราลงกรณ": "vajiralongkorn"}
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", egat_html, re.DOTALL | re.IGNORECASE)
        for r in rows:
            for name, sid in egat_targets.items():
                if name in r and sid not in dam_results:
                    nums = [float(x.replace(",", "")) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", re.sub(r"<[^>]+>", " ", r))]
                    valid = [n for n in nums if 0.0 < n < 300.0]
                    if valid:
                        mld = valid[-1]  # คอลัมน์ระบายน้ำ (ล้าน ลบ.ม./วัน)
                        m3s = round((mld * 1_000_000) / 86400)
                        dam_results[sid] = m3s
                        print(f"   ✓ [Dam Match] {name} ({sid}): {m3s} ลบ.ม./วิ ({mld} ล้าน ลบ.ม./วัน)")

    # 3.2 เขื่อน กรมชลประทาน (ป่าสักฯ, ขุนด่านฯ)
    rid_html = fetch_html_auto_encoding("https://tiwrm.hii.or.th/DATA/REPORT/php/rid_dam.php")
    if rid_html:
        print("📡 [HII RID Dams] เชื่อมต่อสำเร็จ")
        rid_targets = {"ป่าสัก": "pasak", "ขุนด่าน": "khundan"}
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", rid_html, re.DOTALL | re.IGNORECASE)
        for r in rows:
            for name, sid in rid_targets.items():
                if name in r and sid not in dam_results:
                    nums = [float(x.replace(",", "")) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", re.sub(r"<[^>]+>", " ", r))]
                    valid = [n for n in nums if 0.0 < n < 300.0]
                    if valid:
                        mld = valid[-1]
                        m3s = round((mld * 1_000_000) / 86400)
                        dam_results[sid] = m3s
                        print(f"   ✓ [Dam Match] {name} ({sid}): {m3s} ลบ.ม./วิ ({mld} ล้าน ลบ.ม./วัน)")

    return dam_results

# ==============================================================================
# 4. ดึงเขื่อนแม่กลอง (K.10) จาก MK Monitor
# ==============================================================================
def scrape_maeklong_monitor():
    html = fetch_html_auto_encoding("http://mkmonitor.ddns.net/", timeout=10)
    mk_results = {}

    if html:
        print("📡 [MK Monitor DDNS] เชื่อมต่อสำเร็จ")
        clean_html = re.sub(r"สำนักงานชลประทานที่\s*\d+", "", html)

        # วิธีที่ 1: ค้นหาในแถวตาราง <tr>
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", clean_html, re.DOTALL | re.IGNORECASE)
        for r in rows:
            if "แม่กลอง" in r or "K.10" in r or "K10" in r:
                nums = [float(x.replace(",", "")) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", re.sub(r"<[^>]+>", " ", r))]
                valid = [n for n in nums if 50.0 <= n <= 3500.0]
                if valid:
                    mk_results["maeklong_dam"] = round(valid[-1])
                    print(f"   ✓ [MK Monitor Row] เขื่อนแม่กลอง: {mk_results['maeklong_dam']} ลบ.ม./วิ")
                    break

        # วิธีที่ 2: หากไม่ได้อยู่ในตาราง <tr> ให้ค้นหาบล็อกที่อยู่ลึกเกิน 200 ตัวอักษร (ข้ามหัวเว็บ)
        if "maeklong_dam" not in mk_results:
            matches = re.finditer(r"(?:เขื่อนแม่กลอง|K\.?\s*10).{30,800}?(?:ระบาย|ท้ายเขื่อน|ท้าย|Q|ปริมาณน้ำ).*?([0-9]{2,4}(?:,[0-9]{3})*(?:\.[0-9]+)?)", clean_html, re.DOTALL | re.IGNORECASE)
            for m in matches:
                val = float(m.group(1).replace(",", ""))
                if 50.0 <= val <= 3500.0:
                    mk_results["maeklong_dam"] = round(val)
                    print(f"   ✓ [MK Monitor Block] เขื่อนแม่กลอง: {mk_results['maeklong_dam']} ลบ.ม./วิ")
                    break

    return mk_results

# ==============================================================================
# 5. รวมและอัปเดตลง Supabase
# ==============================================================================
def sync_water_data():
    print(f"\n=======================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] กำลังเริ่มกระบวนการซิงค์ข้อมูลน้ำ...")
    print(f"=======================================================")

    flow_data = scrape_hii_chaopraya()
    dam_data = fetch_all_dams()
    mk_data = scrape_maeklong_monitor()

    now_iso = datetime.now(timezone.utc).isoformat()
    payload = []

    for sid, conf in STATIONS_CONFIG.items():
        flow_value = conf["default"]

        # จัดลำดับข้อมูลจริง
        if sid in mk_data:
            flow_value = mk_data[sid]
        elif sid in flow_data:
            flow_value = flow_data[sid]
        elif sid in dam_data:
            flow_value = dam_data[sid]

        # ประเมินสถานะเตือนภัย
        if flow_value >= conf["critical"]:
            status = "critical"
        elif flow_value >= conf["warning"]:
            status = "warning"
        else:
            status = "normal"

        payload.append({
            "station_id": sid,
            "station_name": conf["name"],
            "basin": conf["basin"],
            "discharge_m3s": flow_value,
            "warning_flow": conf["warning"],
            "critical_flow": conf["critical"],
            "status": status,
            "updated_at": now_iso
        })

    try:
        res = supabase.table("water_stations").upsert(payload, on_conflict="station_id").execute()
        print(f"\n✅ ซิงค์สำเร็จสมบูรณ์! อัปเดตข้อมูลจริงลง Supabase ทั้งหมด {len(res.data)} สถานี")
    except Exception as e:
        print(f"\n❌ ผิดพลาดในการส่งข้อมูลเข้า Supabase: {e}")

if __name__ == "__main__":
    sync_water_data()
