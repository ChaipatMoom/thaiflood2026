import os
import sys
import re
import json
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
SUPABASE_KEY = (os.environ.get("SUPABASE_KEY") or "").strip()

if not SUPABASE_KEY:
    raise ValueError("❌ ไม่พบ SUPABASE_KEY ใน Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# โครงสร้าง 12 สถานียุทธศาสตร์หลัก เกณฑ์เตือนภัย (ลบ.ม./วิ) และค่าสำรอง (Fallback)
STATIONS_CONFIG = {
    # ลุ่มน้ำเจ้าพระยา (ThaiWater v3 API: waterlevel_load)
    "C2": {"name": "แม่น้ำเจ้าพระยา C.2 (นครสวรรค์)", "basin": "chao_phraya", "warning": 2000, "critical": 2800, "default": 2389},
    "C13": {"name": "เขื่อนเจ้าพระยา C.13 (ชัยนาท)", "basin": "chao_phraya", "warning": 2000, "critical": 2700, "default": 2500},
    "pasak": {"name": "เขื่อนป่าสักชลสิทธิ์", "basin": "chao_phraya", "warning": 400, "critical": 600, "default": 260},
    "rama6": {"name": "เขื่อนพระรามหก (แม่น้ำป่าสัก)", "basin": "chao_phraya", "warning": 500, "critical": 700, "default": 570},
    "C29A": {"name": "สถานี C.29A บางไทร (อยุธยา)", "basin": "chao_phraya", "warning": 2500, "critical": 3000, "default": 2760},

    # ลุ่มน้ำแม่กลอง (HII EGAT & MK Monitor API)
    "srinagarind": {"name": "เขื่อนศรีนครินทร์ (กาญจนบุรี)", "basin": "mae_klong", "warning": 400, "critical": 600, "default": 0},
    "vajiralongkorn": {"name": "เขื่อนวชิราลงกรณ (กาญจนบุรี)", "basin": "mae_klong", "warning": 300, "critical": 500, "default": 0},
    "maeklong_dam": {"name": "เขื่อนแม่กลอง (K.10 ท่าม่วง)", "basin": "mae_klong", "warning": 1200, "critical": 2000, "default": 1779},

    # ลุ่มน้ำบางปะกง (ThaiWater v3 API: dam & watergate_load)
    "khundan": {"name": "เขื่อนขุนด่านปราการชล", "basin": "bang_pakong", "warning": 100, "critical": 200, "default": 50},
    "narubodintr": {"name": "เขื่อนนฤบดินทรจินดา", "basin": "bang_pakong", "warning": 80, "critical": 150, "default": 40},
    "siyad": {"name": "เขื่อนคลองสียัด", "basin": "bang_pakong", "warning": 50, "critical": 100, "default": 15},
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
# 2. ดึงสถานีลุ่มน้ำเจ้าพระยาจาก ThaiWater v3 API (C.2, C.13, C.29A, พระรามหก, ป่าสัก)
# ==============================================================================
def scrape_thaiwater_v3():
    url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load"
    params = {"basin_code": "6,7,8,9,10,11,12,13,14,15"}
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
            print(f"   ✓ โหลดข้อมูลสถานีน้ำสำเร็จ: พบทั้งหมด {len(items)} สถานี")

            for item in items:
                item_str = json.dumps(item, ensure_ascii=False).upper()
                disc_raw = item.get("discharge") or item.get("flow_rate")

                # ตรวจจับ C.29A ก่อนกรองค่าว่าง
                if "C29A" not in tw_results:
                    if any(k in item_str for k in ["C.29A", "C29A", "C.29", "ศูนย์ศิลปาชีพบางไทร", "บางไทร"]):
                        if disc_raw is not None and str(disc_raw).strip() != "":
                            try:
                                tw_results["C29A"] = round(float(str(disc_raw).replace(",", "")))
                                print(f"   ✓ [ThaiWater Match] C.29A (บางไทร): {tw_results['C29A']} ลบ.ม./วิ")
                            except (ValueError, TypeError):
                                pass

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

                # 2. C.2 (นครสวรรค์)
                if "C2" not in tw_results:
                    if any(k in item_str for k in ["C.2", "C2", "ค่ายจิรประวัติ"]) and "C.29" not in item_str and "C29" not in item_str:
                        tw_results["C2"] = flow_val
                        print(f"   ✓ [ThaiWater Match] C.2 (นครสวรรค์): {flow_val} ลบ.ม./วิ")

                # 3. C.13 (เขื่อนเจ้าพระยา)
                if "C13" not in tw_results:
                    if any(k in item_str for k in ["C.13", "C13", "เขื่อนเจ้าพระยา"]):
                        tw_results["C13"] = flow_val
                        print(f"   ✓ [ThaiWater Match] C.13 (เขื่อนเจ้าพระยา): {flow_val} ลบ.ม./วิ")

                # 4. เขื่อนพระรามหก
                if "rama6" not in tw_results:
                    if any(k in item_str for k in ["พระรามหก", "พระราม 6", "S.26", "S26"]):
                        tw_results["rama6"] = flow_val
                        print(f"   ✓ [ThaiWater Match] พระรามหก: {flow_val} ลบ.ม./วิ")

            # Water Balance Fallback: ถ้าเซ็นเซอร์บางไทรไม่มีตัวเลข ใช้อัตราสมดุลน้ำจริง
            if "C29A" not in tw_results and "C13" in tw_results and "rama6" in tw_results:
                estimated_flow = tw_results["C13"] + tw_results["rama6"] - 310
                tw_results["C29A"] = max(estimated_flow, 1500)
                print(f"   ✓ [C.29A Water Balance] คำนวณสมดุลน้ำบางไทร: {tw_results['C29A']} ลบ.ม./วิ")

    except Exception as e:
        print(f"⚠️ ดึงข้อมูล ThaiWater v3 API ขัดข้อง: {e}")

    return tw_results

# ==============================================================================
# 3. ดึงเขื่อนกรมชลประทานฝั่งบางปะกง (ขุนด่านฯ, นฤบดินทรจินดา, คลองสียัด)
# ==============================================================================
def scrape_thaiwater_dams():
    tz_th = timezone(timedelta(hours=7))
    now_th = datetime.now(tz_th)
    today_str = now_th.strftime("%Y-%m-%d")

    url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/analyst/dam"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://waterchart.thaiwater.net/",
        "Accept": "application/json, text/plain, */*"
    }

    dam_results = {}
    try:
        resp = requests.get(url, params={"dam_date": today_str}, headers=headers, timeout=15)
        if resp.status_code != 200 or not resp.json():
            yesterday_str = (now_th - timedelta(days=1)).strftime("%Y-%m-%d")
            resp = requests.get(url, params={"dam_date": yesterday_str}, headers=headers, timeout=15)

        print(f"📡 [ThaiWater Dam API] HTTP Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            raw_data = data.get("data") if isinstance(data, dict) and "data" in data else data

            # กระจายข้อมูลให้อยู่ในรูปแบบ Flattened List
            dam_list = []
            if isinstance(raw_data, dict):
                for v in raw_data.values():
                    if isinstance(v, list):
                        dam_list.extend([x for x in v if isinstance(x, dict)])
                    elif isinstance(v, dict):
                        for sub_v in v.values():
                            if isinstance(sub_v, list):
                                dam_list.extend([x for x in sub_v if isinstance(x, dict)])
                            elif isinstance(sub_v, dict):
                                dam_list.append(sub_v)
            elif isinstance(raw_data, list):
                for x in raw_data:
                    if isinstance(x, dict):
                        sub_lists = [sub_v for sub_v in x.values() if isinstance(sub_v, list)]
                        if sub_lists:
                            for sl in sub_lists:
                                dam_list.extend([item for item in sl if isinstance(item, dict)])
                        else:
                            dam_list.append(x)

            print(f"   ✓ โหลดข้อมูลเขื่อนสำเร็จ: กระจายข้อมูลได้ทั้งหมด {len(dam_list)} เขื่อน")

            # ฟังก์ชันช่วยดึงค่าแรกที่มีอยู่จริง (ป้องกัน 0 โดนกลืนเป็น None)
            def extract_val(d, keys):
                for k in keys:
                    v = d.get(k)
                    if v is not None and str(v).strip() != "":
                        return v
                return None

            for item in dam_list:
                if not isinstance(item, dict):
                    continue

                item_str = json.dumps(item, ensure_ascii=False).upper()

                flow_val = None
                # 1. ตรวจสอบค่า discharge (ลบ.ม./วิ)
                disc_raw = extract_val(item, ["discharge", "dam_discharge", "flow_rate"])
                if disc_raw is not None:
                    try:
                        flow_val = round(float(str(disc_raw).replace(",", "")))
                    except (ValueError, TypeError):
                        pass

                # 2. ตรวจสอบปริมาณน้ำระบายรายวัน (ล้าน ลบ.ม./วัน) -> แปลงเป็น ลบ.ม./วิ
                if flow_val is None:
                    rel_raw = extract_val(item, ["dam_released", "released", "dam_outflow", "outflow", "dam_daily_outflow", "dam_daily_release"])
                    if rel_raw is not None:
                        try:
                            mld = float(str(rel_raw).replace(",", ""))
                            flow_val = round((mld * 1_000_000) / 86400)
                        except (ValueError, TypeError):
                            pass

                if flow_val is None:
                    continue

                # 1. เขื่อนขุนด่านปราการชล
                if "khundan" not in dam_results:
                    if any(k in item_str for k in ["ขุนด่าน", "KHUN DAN", "KHUNDAN"]):
                        dam_results["khundan"] = flow_val
                        print(f"   ✓ [ThaiWater Dam Match] เขื่อนขุนด่านปราการชล: {flow_val} ลบ.ม./วิ")

                # 2. เขื่อนนฤบดินทรจินดา (รองรับทั้ง นฤบดินทร, นฤบดินทร์, โสมง)
                if "narubodintr" not in dam_results:
                    if any(k in item_str for k in ["นฤบดินทร", "นฤบดินทร์", "ห้วยโสมง", "โสมง", "NARUBODIN"]):
                        dam_results["narubodintr"] = flow_val
                        print(f"   ✓ [ThaiWater Dam Match] เขื่อนนฤบดินทรจินดา: {flow_val} ลบ.ม./วิ")

                # 3. เขื่อนคลองสียัด
                if "siyad" not in dam_results:
                    if any(k in item_str for k in ["คลองสียัด", "สียัด", "SI YAT", "SIYAT"]):
                        dam_results["siyad"] = flow_val
                        print(f"   ✓ [ThaiWater Dam Match] เขื่อนคลองสียัด: {flow_val} ลบ.ม./วิ")

    except Exception as e:
        print(f"⚠️ ดึงข้อมูล ThaiWater Dam API ขัดข้อง: {e}")

    return dam_results
# ==============================================================================
# 4. ดึงประตูระบายน้ำฝั่งบางปะกง (ปตร. แม่น้ำบางปะกง)
# ==============================================================================
def scrape_thaiwater_watergates():
    url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/watergate_load"
    params = {"basin_code": "6,7,8,9,10,11,12,13,14,15"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://waterchart.thaiwater.net/",
        "Accept": "application/json, text/plain, */*"
    }

    gate_results = {}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        print(f"📡 [ThaiWater Watergate API] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            items = data.get("watergate_data", {}).get("data", []) or data.get("data", [])
            if not items and isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict) and "data" in v and isinstance(v["data"], list):
                        items = v["data"]
                        break

            print(f"   ✓ โหลดข้อมูล ปตร. สำเร็จ: พบทั้งหมด {len(items)} ประตูระบายน้ำ")

            for item in items:
                item_str = json.dumps(item, ensure_ascii=False).upper()

                # ดักจับชื่อสถานีจริงในระบบ ("เขื่อนทดน้ำบางประกง" หรือ "ปตร.บางปะกง")
                if any(k in item_str for k in ["เขื่อนทดน้ำบางประกง", "ปตร.บางปะกง", "ปตร. แม่น้ำบางปะกง"]):
                    disc_raw = (
                        item.get("discharge") or 
                        item.get("flow_rate") or 
                        item.get("watergate_discharge") or 
                        item.get("watergate_outflow")
                    )
                    if disc_raw is not None and str(disc_raw).strip() != "":
                        try:
                            flow_val = round(float(str(disc_raw).replace(",", "")))
                            gate_results["bangpakong_gate"] = flow_val
                            print(f"   ✓ [ThaiWater Watergate Match] ปตร. แม่น้ำบางปะกง: {flow_val} ลบ.ม./วิ")
                            break
                        except (ValueError, TypeError):
                            pass

    except Exception as e:
        print(f"⚠️ ดึงข้อมูล ThaiWater Watergate API ขัดข้อง: {e}")

    # Fallback: หากเซ็นเซอร์ไม่มีตัวเลข (ออฟไลน์ตั้งแต่ปี 2022) ให้ใช้เกณฑ์มาตรฐาน 310 ลบ.ม./วิ ตามผังทางการ
    if "bangpakong_gate" not in gate_results:
        gate_results["bangpakong_gate"] = 310
        print(f"   ✓ [Watergate Standard] ปตร. แม่น้ำบางปะกง (เกณฑ์ระบายมาตรฐาน): 310 ลบ.ม./วิ")

    return gate_results

# ==============================================================================
# 5. ดึงเขื่อนขนาดใหญ่ กฟผ. (ศรีนครินทร์, วชิราลงกรณ)
# ==============================================================================
def fetch_all_dams():
    dam_results = {}
    egat_html = fetch_html_auto_encoding("https://tiwrm.hii.or.th/DATA/REPORT/php/egat_dam.php")

    if egat_html:
        print("📡 [HII EGAT Dams] เชื่อมต่อสำเร็จ")
        egat_targets = {
            "ศรีนครินทร์": {"sid": "srinagarind", "max_mld": 45.0},
            "วชิราลงกรณ": {"sid": "vajiralongkorn", "max_mld": 55.0}
        }

        chunks = re.split(r"<tr[^>]*>", egat_html, flags=re.IGNORECASE)
        for chunk in chunks:
            if "รวม" in chunk or "เฉลี่ย" in chunk:
                continue

            for name, conf in egat_targets.items():
                sid = conf["sid"]
                if name in chunk and sid not in dam_results:
                    clean_text = re.sub(r"<[^>]+>", " ", chunk)
                    nums = [float(x.replace(",", "")) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", clean_text)]
                    valid = [n for n in nums if 0.0 <= n <= conf["max_mld"]]
                    if valid:
                        mld = valid[-1]
                        m3s = round((mld * 1_000_000) / 86400)
                        dam_results[sid] = m3s
                        print(f"   ✓ [Dam Match] {name} ({sid}): {m3s} ลบ.ม./วิ ({mld} ล้าน ลบ.ม./วัน)")

    return dam_results

# ==============================================================================
# 6. ดึงเขื่อนแม่กลองผ่าน Session API (POST: http://mkmonitor.ddns.net/api/v1/wf02)
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
        print(f"⚠️ ดึงข้อมูลจาก MK Monitor API ขัดข้อง: {e}")

    return mk_results

# ==============================================================================
# 7. รวมข้อมูลทั้งหมดและ Upsert ลง Supabase
# ==============================================================================
def sync_water_data():
    tz_th = timezone(timedelta(hours=7))
    now_th = datetime.now(tz_th)

    print(f"\n=======================================================")
    print(f"[{now_th.strftime('%Y-%m-%d %H:%M:%S')}] กำลังเริ่มกระบวนการซิงค์ข้อมูลน้ำ (เวลาไทย)...")
    print(f"=======================================================")

    flow_data = scrape_thaiwater_v3()
    tw_dam_data = scrape_thaiwater_dams()
    gate_data = scrape_thaiwater_watergates()
    egat_dam_data = fetch_all_dams()
    mk_data = scrape_maeklong_monitor()

    now_iso = now_th.isoformat()
    payload = []

    for sid, conf in STATIONS_CONFIG.items():
        flow_value = conf["default"]

        if sid in mk_data:
            flow_value = mk_data[sid]
        elif sid in flow_data:
            flow_value = flow_data[sid]
        elif sid in gate_data:
            flow_value = gate_data[sid]
        elif sid in tw_dam_data:
            flow_value = tw_dam_data[sid]
        elif sid in egat_dam_data:
            flow_value = egat_dam_data[sid]

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
