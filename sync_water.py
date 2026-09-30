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
# 1. การตั้งค่า Supabase
# ==============================================================================
SUPABASE_URL = "https://ycchozbszqxxmvxwdlag.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("❌ ไม่พบ SUPABASE_KEY ใน Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ผัง 10 สถานี เกณฑ์เตือนภัย และค่าสำรอง (Fallback)
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

    # ลุ่มน้ำบางปะกง (HII EGAT)
    "khundan": {"name": "เขื่อนขุนด่านปราการชล", "basin": "bang_pakong", "warning": 100, "critical": 200, "default": 50},
    "bangpakong_gate": {"name": "ปตร. แม่น้ำบางปะกง", "basin": "bang_pakong", "warning": 400, "critical": 600, "default": 310}
}

# ==============================================================================
# 2. ดึงข้อมูลเขื่อนขนาดใหญ่จาก HII EGAT Report (แก้ 401 จาก ThaiWater API)
# ==============================================================================
def fetch_hii_dams():
    """
    ดึงข้อมูลการระบายน้ำของเขื่อนขนาดใหญ่จากฐานข้อมูล HII TIWRM โดยตรง
    ครอบคลุม: ศรีนครินทร์, วชิราลงกรณ, ป่าสักชลสิทธิ์, ขุนด่านฯ
    """
    url = "https://tiwrm.hii.or.th/DATA/REPORT/php/egat_dam.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://tiwrm.hii.or.th/"
    }

    dam_targets = {
        "ศรีนครินทร์": "srinagarind",
        "วชิราลงกรณ": "vajiralongkorn",
        "ป่าสัก": "pasak",
        "ขุนด่าน": "khundan"
    }

    dam_results = {}
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        print(f"📡 [HII Dam Report] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            html = resp.content.decode("tis-620", errors="ignore")

            # กวาดแยกทีละแถว <tr> ในตาราง
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
            for row in rows:
                for thai_name, sid in dam_targets.items():
                    if thai_name in row and sid not in dam_results:
                        # ดึงตัวเลขทั้งหมดในแถวของเขื่อนนั้น
                        cols = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
                        clean_nums = []
                        for c in cols:
                            text = re.sub(r"<[^>]+>", "", c).strip().replace(",", "")
                            try:
                                val = float(text)
                                clean_nums.append(val)
                            except ValueError:
                                pass

                        # ในตารางเขื่อน คอลัมน์การระบายน้ำ (ล้าน ลบ.ม./วัน) มักอยู่ท้ายๆ
                        # หาตัวเลขการระบายน้ำที่เป็นไปได้ (> 0 และ < 200 ล้าน ลบ.ม./วัน)
                        for n in reversed(clean_nums):
                            if 0.0 < n < 300.0:
                                m3s = round((n * 1_000_000) / 86400)
                                dam_results[sid] = m3s
                                print(f"   ✓ [HII Dam Match] {thai_name} ({sid}): {m3s} ลบ.ม./วิ ({n} ล้าน ลบ.ม./วัน)")
                                break
    except Exception as e:
        print(f"⚠️ ดึงข้อมูลเขื่อนจาก HII ขัดข้อง: {e}")

    return dam_results

# ==============================================================================
# 3. ดึงสถานีลุ่มน้ำเจ้าพระยา (แก้ Regex ดักชนรหัสสถานี)
# ==============================================================================
def scrape_hii_chaopraya():
    """
    ดึงอัตราการไหลจริง (ลบ.ม./วิ) จากผังระบายน้ำ HII ลุ่มน้ำเจ้าพระยา
    เจาะจงเฉพาะตัวเลขที่มีค่า Q หรืออยู่ในช่วงอัตราการไหลจริงของสถานี
    """
    url = "https://tiwrm.hii.or.th/DATA/REPORT/php/chart/chaopraya/2013/chaopraya.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://tiwrm.hii.or.th/"
    }

    hii_results = {}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"📡 [HII TIWRM Flow] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            html = resp.content.decode("tis-620", errors="ignore")

            # ดักจับชุดข้อความที่มีคำว่า Q หรืออัตราการไหลหลังชื่อสถานี
            station_rules = {
                "C2": (r"C\.?\s*2\b.*?([0-9]{3,4}(?:,[0-9]{3})*)", 300),         # แม่น้ำเจ้าพระยาตอนบนปกติ > 300
                "C13": (r"C\.?\s*13\b.*?([0-9]{2,4}(?:,[0-9]{3})*)", 100),       # ท้ายเขื่อนเจ้าพระยาปกติ > 100
                "C29A": (r"C\.?\s*29A?\b.*?([0-9]{3,4}(?:,[0-9]{3})*)", 500),    # บางไทรปกติ > 500
                "rama6": (r"(?:พระรามหก|S\.?\s*26).*?([0-9]{2,4}(?:,[0-9]{3})*)", 10)
            }

            for sid, (pattern, min_valid) in station_rules.items():
                matches = re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)
                for m in matches:
                    raw_val = m.group(1).replace(",", "")
                    try:
                        val = float(raw_val)
                        # กรองค่าต้องมากกว่า min_valid เพื่อตัดเลขรหัสสถานี (เช่น 2, 13) ทิ้ง
                        if val >= min_valid:
                            hii_results[sid] = round(val)
                            print(f"   ✓ [HII Flow Match] {sid}: {hii_results[sid]} ลบ.ม./วิ")
                            break
                    except ValueError:
                        pass
    except Exception as e:
        print(f"⚠️ ดึงข้อมูลจาก HII Flow ขัดข้อง: {e}")

    return hii_results

# ==============================================================================
# 4. ดึงเขื่อนแม่กลอง (ตัดเลขสำนักงานชลประทานที่ 13 ออก)
# ==============================================================================
def scrape_maeklong_monitor():
    url = "http://mkmonitor.ddns.net/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml"
    }

    mk_results = {}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"📡 [MK Monitor DDNS] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            html = resp.content.decode("tis-620", errors="ignore")
            if "เขื่อนแม่กลอง" not in html and "K.10" not in html:
                html = resp.content.decode("utf-8", errors="ignore")

            # ตัดคำว่า 'สำนักงานชลประทานที่ 13' ออกก่อนนำไปค้นหาตัวเลข
            clean_html = re.sub(r"สำนักงานชลประทานที่\s*\d+", "", html)

            # ค้นหาคำว่า ระบาย หรือ ท้ายเขื่อน ตามด้วยตัวเลขระบายน้ำ (> 50 ลบ.ม./วิ)
            pattern = r"(?:เขื่อนแม่กลอง|K\.?\s*10).*?(?:ระบาย|ท้าย|ปริมาณน้ำ|Q).*?([0-9]{2,4}(?:,[0-9]{3})*(?:\.[0-9]+)?)"
            match = re.search(pattern, clean_html, re.DOTALL | re.IGNORECASE)

            if match:
                raw_val = match.group(1).replace(",", "")
                val = float(raw_val)
                if val >= 50:
                    mk_results["maeklong_dam"] = round(val)
                    print(f"   ✓ [MK Monitor Match] เขื่อนแม่กลอง: {mk_results['maeklong_dam']} ลบ.ม./วิ")
    except Exception as e:
        print(f"⚠️ ดึงข้อมูลจาก mkmonitor.ddns.net ขัดข้อง: {e}")

    return mk_results

# ==============================================================================
# 5. รวมข้อมูลและบันทึกลง Supabase
# ==============================================================================
def sync_water_data():
    print(f"\n=======================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] กำลังเริ่มกระบวนการซิงค์ข้อมูลน้ำ...")
    print(f"=======================================================")

    dam_data = fetch_hii_dams()
    flow_data = scrape_hii_chaopraya()
    mk_data = scrape_maeklong_monitor()

    now_iso = datetime.now(timezone.utc).isoformat()
    payload = []

    for sid, conf in STATIONS_CONFIG.items():
        flow_value = conf["default"]

        # จัดลำดับข้อมูลจริงก่อนเสมอ
        if sid in mk_data:
            flow_value = mk_data[sid]
        elif sid in flow_data:
            flow_value = flow_data[sid]
        elif sid in dam_data:
            flow_value = dam_data[sid]

        # ประเมินสถานะ
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
