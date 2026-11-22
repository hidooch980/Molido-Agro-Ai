from __future__ import annotations

import time
from typing import Any, Literal
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

# Certified greenhouse food crop disease knowledge base
DISEASE_KNOWLEDGE_BASE = {
    "cucumber": {
        "cuc-downy-mildew": {
            "persian_name": "سفیدک داخلی (دروغی) خیار",
            "scientific_name": "Pseudoperonospora cubensis",
            "optimal_temp_range": (18, 25),
            "critical_humidity": 80.0,
            "ipm_cultural": [
                "کاهش رطوبت نسبی گلخانه به زیر ۸۰٪ با تهویه اصولی",
                "اجتناب از آبیاری بارانی یا خیس شدن بوته‌ها در عصرگاه",
                "هرس برگ‌های پیر کف بوته و خروج ایمن از گلخانه"
            ],
            "ipm_biological": [
                "محلول‌پاشی بیوکنترل باسیلوس سوبتیلیس",
                "فسفیت پتاسیم جهت القای مقاومت سیستمیک"
            ],
            "risk_level": "HIGH",
            "safety_advisory": "مصرف قارچ‌کش‌های شیمیایی تنها با نسخه کارشناس رسمی حفظ نباتات و رعایت دقیق دوره کارنس (PHI) مجاز است."
        },
        "cuc-powdery-mildew": {
            "persian_name": "سفیدک سطحی (پودری) خیار",
            "scientific_name": "Podosphaera xanthii",
            "optimal_temp_range": (20, 28),
            "critical_humidity": 65.0,
            "ipm_cultural": [
                "تنظیم فاصله کشت بوته‌ها برای تهویه مطلوب",
                "پرهیز از مصرف بیش از حد کودهای ازته"
            ],
            "ipm_biological": [
                "گوگرد میکرونیزه و وتابل در دمای زیر ۲۸ درجه سانتی‌گراد",
                "روغن گیاهی چریش (Neem oil)"
            ],
            "risk_level": "MEDIUM",
            "safety_advisory": "از پاشش گوگرد در ساعات گرم روز پرهیز کنید تا از سوختگی بوته جلوگیری شود."
        }
    },
    "tomato": {
        "tom-late-blight": {
            "persian_name": "بادزدگی (سوختگی دیرهنگام) گوجه‌فرنگی",
            "scientific_name": "Phytophthora infestans",
            "optimal_temp_range": (15, 22),
            "critical_humidity": 85.0,
            "ipm_cultural": [
                "کنترل جدی رطوبت هوای گلخانه با حرارت و تهویه تلفیقی",
                "ضدعفونی قیچی هرس پس از هر ردیف",
                "معدوم‌سازی بوته‌های آلوده اولیه در کیسه دربسته"
            ],
            "ipm_biological": [
                "قارچ‌های تریکودرما (Trichoderma harzianum) در خاک",
                "مس کلاته در مراحل پیشگیری"
            ],
            "risk_level": "HIGH",
            "safety_advisory": "در صورت شیوع سریع، مداخله کارشناس کلینیک گیاه‌پزشکی الزامی است."
        }
    },
    "strawberry": {
        "str-gray-mold": {
            "persian_name": "کپک خاکستری توت‌فرنگی (بوتریتیس)",
            "scientific_name": "Botrytis cinerea",
            "optimal_temp_range": (15, 23),
            "critical_humidity": 85.0,
            "ipm_cultural": [
                "برداشت به موقع میوه‌های رسیده بدون باقی‌ماندن روی بوته",
                "تهویه فعال شبانه برای جلوگیری از تشکیل قطرات شبنم روی میوه"
            ],
            "ipm_biological": [
                "میکروارگانیسم‌های آنتاگونیست مجاز ارگانیک"
            ],
            "risk_level": "HIGH",
            "safety_advisory": "توت‌فرنگی مستقیماً به مصرف تازه می‌رسد؛ اولویت قطعی با روش‌های غیرشیمیایی است."
        }
    }
}


class DiagnosisRequest(BaseModel):
    cropCode: Literal["cucumber", "tomato", "eggplant", "pepper", "strawberry", "lettuce", "herbs", "melon", "watermelon", "zucchini"]
    diseaseId: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    greenhouseId: str | None = None
    notes: str = Field(default="", max_length=1000)


def register_ai_diagnostics_routes(app: FastAPI, db_getter, current_user_getter, decrypt_payload_fn=None) -> None:
    @app.post("/v1/ai/diagnose/disease")
    def diagnose_crop_disease(req: DiagnosisRequest, authorization: str | None = Header(default=None)):
        uid = current_user_getter(authorization)

        # Microclimate telemetry context from sensors (if greenhouseId is given)
        sensor_temp: float | None = None
        sensor_humidity: float | None = None
        if req.greenhouseId and decrypt_payload_fn:
            with db_getter() as conn:
                has_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='greenhouse_sensor_readings'").fetchone()
                if has_table:
                    latest = conn.execute(
                        """
                        SELECT payload FROM greenhouse_sensor_readings
                        WHERE user_id = ? AND greenhouse_id = ?
                        ORDER BY measured_at DESC, id DESC LIMIT 1
                        """,
                        (uid, req.greenhouseId)
                    ).fetchone()
                    if latest:
                        try:
                            decrypted = decrypt_payload_fn(latest["payload"])
                            sensor_temp = float(decrypted.get("temperatureC", 0))
                            sensor_humidity = float(decrypted.get("relativeHumidityPct", 0))
                        except Exception:
                            pass

        crop_kb = DISEASE_KNOWLEDGE_BASE.get(req.cropCode, {})
        disease = crop_kb.get(req.diseaseId or "")

        # Confidence Gate
        if req.confidence < 0.70 or not disease:
            return {
                "status": "inconclusive",
                "cropCode": req.cropCode,
                "confidence": req.confidence,
                "condition": disease["persian_name"] if disease else "تشخیص نامشخص یا اطمینان ناکافی",
                "riskLevel": "ELEVATED_UNCERTAINTY",
                "microclimate": {
                    "temperatureCelsius": sensor_temp,
                    "humidityPercent": sensor_humidity,
                },
                "culturalControls": [
                    "تصویربرداری مجدد با وضوح بالاتر و نور یکنواخت روز",
                    "بررسی وضعیت رطوبت بستر و پایش تهویه گلخانه",
                    "ارسال نمونه مشکوک به کارشناس گیاه‌پزشک"
                ],
                "biologicalControls": [],
                "safetyAdvisory": "ضریب اطمینان ناکافی است؛ هرگونه سم‌پاشی شیمیایی بدون تأیید آزمایشگاهی ممنوع است.",
                "requiresHumanSignoff": True,
                "timestamp": int(time.time() * 1000)
            }

        # Microclimate Risk Escalation
        risk_level = disease["risk_level"]
        microclimate_risk_alert = None
        if sensor_humidity is not None and sensor_temp is not None:
            min_t, max_t = disease["optimal_temp_range"]
            if min_t <= sensor_temp <= max_t and sensor_humidity >= disease["critical_humidity"]:
                microclimate_risk_alert = f"هشدار اقلیمی: دمای {sensor_temp}°C و رطوبت {sensor_humidity}٪ در محدوده بحرانی طغیان این بیماری است."
                risk_level = "CRITICAL"

        return {
            "status": "diagnosed",
            "cropCode": req.cropCode,
            "diseaseId": req.diseaseId,
            "condition": disease["persian_name"],
            "scientificName": disease["scientific_name"],
            "confidence": req.confidence,
            "riskLevel": risk_level,
            "microclimate": {
                "temperatureCelsius": sensor_temp,
                "humidityPercent": sensor_humidity,
                "alert": microclimate_risk_alert
            },
            "culturalControls": disease["ipm_cultural"],
            "biologicalControls": disease["ipm_biological"],
            "safetyAdvisory": disease["safety_advisory"],
            "requiresHumanSignoff": risk_level in ("HIGH", "CRITICAL"),
            "timestamp": int(time.time() * 1000)
        }
