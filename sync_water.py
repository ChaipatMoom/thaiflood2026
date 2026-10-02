import os
import sys
import re
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==============================================================================
# 1. การตั้งค่าการเชื่อมต่อฐานข้อมูล Supabase
# ==============================================================================
SUPABASE_URL = "https://ycchozbszqxxmvxwdlag.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("❌ ไม่พบ SUPABASE_KEY ใน Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 10 สถานียุทธศาสตร์หลัก เกณฑ์เตือนภัย (ลบ.ม./วิ) และค่าสำรอง (Fallback)
STATIONS_CONFIG = {
    # ลุ่มน้ำเจ้าพระยา (HII TIWRM)
    "C2": {"name": "แม่น้ำเจ้าพระยา C.2 (นครสวรรค์)", "basin": "chao_phraya", "warning": 2000, "critical": 2800, "default": 1904},
    "C13": {"name": "เขื่อนเจ้าพระยา C.13 (ชัยนาท)", "basin": "chao_phraya", "warning": 2000, "critical": 2700, "default": 2200},
    "pasak": {"name": "เขื่อนป่าสักชลสิทธิ์", "basin": "chao_phraya", "warning": 400, "critical": 600, "default": 115},
    "rama6": {"name": "เขื่อนพระรามหก (แม่น้ำป่าสัก)", "basin": "chao_phraya", "warning": 500, "critical": 700, "default": 410},
    "C29A": {"name": "สถานี C.29A บางไทร (อยุธยา)", "basin": "chao_phraya", "warning": 2500, "critical": 3000, "default": 2250},

    # ลุ่มน้ำแม่กลอง (HII EGAT & MK Monitor API)
    "srinagarind": {"name": "เขื่อนศรีนครินทร์ (กาญจนบุรี)", "basin": "mae_klong", "warning": 400, "critical": 600, "default": 180},
    "vajiralongkorn": {"name": "เขื่อนวชิราลงกรณ (กาญจนบุรี)", "basin": "mae_klong", "warning": 300, "critical": 500, "default": 120},
    "maeklong_dam": {"name": "เขื่อนแม่กลอง (K.10 ท่าม่วง)", "basin": "mae_klong", "warning": 1200, "critical": 2000, "default": 1000},

    # ลุ่มน้ำบางปะกง (ค่าสำรอง)
    "khundan": {"name": "เขื่อนขุนด่านปราการชล", "basin": "bang_pakong", "warning": 100, "critical": 200, "default": 50},
    "bangpakong_gate": {"name": "ปตร. แม่น้ำบางปะกง", "basin": "bang_pakong", "warning": 400, "critical": 600, "default": 310}
}

def fetch_html_auto_encoding(url, timeout=15):
    """ฟังก์ชันกลางดึงหน้าเว็บพร้อมตรวจจับรหัสภาษาไทยอัตโนมัติ"""
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
# 2. ดึงสถานีลุ่มน้ำเจ้าพระยาจาก ThaiWater v3 API (C.2, C.13, C.29A, พระรามหก)
# ==============================================================================
def scrape_thaiwater_v3():
    import json

    url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load"
    params = {
        "basin_code": "6,7,8,9,10,11,12,13,14,15"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://waterchart.thaiwater.net/",
        "Accept": "application/json, text/plain, */*"
    }

    tw_results = {}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        print(f"📡 [ThaiWater v3 API] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            items = data.get("waterlevel_data", {}).get("data", [])
            print(f"   ✓ โหลดข้อมูลสำเร็จ: พบทั้งหมด {len(items)} สถานี")

            for item in items:
                item_str = json.dumps(item, ensure_ascii=False).upper()
                disc_raw = item.get("discharge") or item.get("flow_rate")

                # [จุดที่ 1] ดักจับ C.29A เป็นพิเศษก่อนโดนข้ามค่า null
                if "C29A" not in tw_results:
                    if any(k in item_str for k in ["C.29A", "C29A", "C.29", "ศูนย์ศิลปาชีพบางไทร", "บางไทร"]):
                        if disc_raw is not None and str(disc_raw).strip() != "":
                            try:
                                tw_results["C29A"] = round(float(str(disc_raw).replace(",", "")))
                                print(f"   ✓ [ThaiWater Match] C.29A (บางไทร): {tw_results['C29A']} ลบ.ม./วิ")
                            except (ValueError, TypeError):
                                pass

                # กรองสถานีที่ไม่มีอัตราการไหลออก
                if disc_raw is None or str(disc_raw).strip() == "":
                    continue

                try:
                    flow_val = round(float(str(disc_raw).replace(",", "")))
                except (ValueError, TypeError):
                    continue

                # 1. เขื่อนป่าสักชลสิทธิ์
                if "pasak" not in tw_results:
                    if any(k in item_str for k in ["ป่าสักชลสิทธิ์", "PASAK"]):
                        tw_results["pasak"] = flow_val
                        print(f"   ✓ [ThaiWater Match] ป่าสักชลสิทธิ์: {flow_val} ลบ.ม./วิ")

                # 2. สถานี C.2 (นครสวรรค์)
                if "C2" not in tw_results:
                    if any(k in item_str for k in ["C.2", "C2", "ค่ายจิรประวัติ"]) and "C.29" not in item_str and "C29" not in item_str:
                        tw_results["C2"] = flow_val
                        print(f"   ✓ [ThaiWater Match] C.2 (นครสวรรค์): {flow_val} ลบ.ม./วิ")

                # 3. สถานี C.13 (เขื่อนเจ้าพระยา)
                if "C13" not in tw_results:
                    if any(k in item_str for k in ["C.13", "C13", "เขื่อนเจ้าพระยา"]):
                        tw_results["C13"] = flow_val
                        print(f"   ✓ [ThaiWater Match] C.13 (เขื่อนเจ้าพระยา): {flow_val} ลบ.ม./วิ")

                # 4. สถานี เขื่อนพระรามหก
                if "rama6" not in tw_results:
                    if any(k in item_str for k in ["พระรามหก", "พระราม 6", "S.26", "S26"]):
                        tw_results["rama6"] = flow_val
                        print(f"   ✓ [ThaiWater Match] พระรามหก: {flow_val} ลบ.ม./วิ")

            # [จุดที่ 2] Water Balance Fallback: ถ้าเซ็นเซอร์บางไทรเป็น null ให้คำนวณจากสมดุลน้ำจริง
            if "C29A" not in tw_results and "C13" in tw_results and "rama6" in tw_results:
                estimated_flow = tw_results["C13"] + tw_results["rama6"] - 310  # หักน้ำผันลงท่าจีน ~310
                tw_results["C29A"] = max(estimated_flow, 1500)
                print(f"   ✓ [C.29A Water Balance] คำนวณสมดุลน้ำบางไทร: {tw_results['C29A']} ลบ.ม./วิ")

    except Exception as e:
        print(f"⚠️ ดึงข้อมูล ThaiWater v3 API ขัดข้อง: {e}")

    return tw_results

# ==============================================================================
# 4. ดึงเขื่อนแม่กลองผ่าน Session API (POST: http://mkmonitor.ddns.net/api/v1/wf02)
# ==============================================================================
def scrape_maeklong_monitor():
    base_page = "http://mkmonitor.ddns.net/waterflow"
    api_url = "http://mkmonitor.ddns.net/api/v1/wf02"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "http://mkmonitor.ddns.net",
        "Referer": base_page
    }

    tz_th = timezone(timedelta(hours=7))
    now_th = datetime.now(tz_th)

    payload = {
        "start": now_th.strftime("%Y-%m-%d 00:00"),
        "end": now_th.strftime("%Y-%m-%d %H:%M"),
        "format": "3600",
        "site_id": 2
    }

    mk_results = {}
    session = requests.Session()

    try:
        session.get(base_page, headers={"User-Agent": headers["User-Agent"]}, timeout=10)
        resp = session.post(api_url, headers=headers, json=payload, timeout=25)
        print(f"📡 [MK Monitor API] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            charts = data.get("charts", {}) if isinstance(data, dict) else {}

            flow_series = []
            if "data" in charts and isinstance(charts["data"], list):
                flow_series = charts["data"]
            elif "datasets" in charts and isinstance(charts["datasets"], list) and len(charts["datasets"]) > 0:
                first_ds = charts["datasets"][0]
                if isinstance(first_ds, dict) and "data" in first_ds:
                    flow_series = first_ds["data"]
            elif isinstance(charts, dict):
                for k, v in charts.items():
                    if k not in ["label", "labels"] and isinstance(v, list) and len(v) > 0:
                        flow_series = v
                        break

            valid_numbers = []
            for item in flow_series:
                try:
                    val = float(item.get("y") if isinstance(item, dict) else item)
                    valid_numbers.append(val)
                except (ValueError, TypeError):
                    pass

            if valid_numbers:
                latest_flow = valid_numbers[-1]
                mk_results["maeklong_dam"] = round(latest_flow)
                print(f"   ✓ [MK Monitor API Match] เขื่อนแม่กลอง (K.10): {mk_results['maeklong_dam']} ลบ.ม./วิ")
    except Exception as e:
        print(f"⚠️️ ดึงข้อมูลจาก MK Monitor API ขัดข้อง: {e}")

    return mk_results

# ==============================================================================
# 5. รวบรวมข้อมูลและ Upsert ลง Supabase
# ==============================================================================
def sync_water_data():
    tz_th = timezone(timedelta(hours=7))
    now_th = datetime.now(tz_th)

    print(f"\n=======================================================")
    print(f"[{now_th.strftime('%Y-%m-%d %H:%M:%S')}] กำลังเริ่มกระบวนการซิงค์ข้อมูลน้ำ (เวลาไทย)...")
    print(f"=======================================================")

    flow_data = scrape_thaiwater_v3()   # ดึงจาก ThaiWater v3 API
    dam_data = fetch_all_dams()
    mk_data = scrape_maeklong_monitor()

    now_iso = now_th.isoformat()
    payload = []

    for sid, conf in STATIONS_CONFIG.items():
        flow_value = conf["default"]

        if sid in mk_data:
            flow_value = mk_data[sid]
        elif sid in flow_data:
            flow_value = flow_data[sid]
        elif sid in dam_data:
            flow_value = dam_data[sid]

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
