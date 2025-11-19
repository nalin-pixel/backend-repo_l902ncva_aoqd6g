import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="Digital Plant Growth & Care System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility helpers

def oid(id_str: str) -> ObjectId:
    return ObjectId(id_str)


def serialize(doc):
    if not doc:
        return doc
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    # convert datetime
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


def clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


# Schemas endpoint for builder viewers
@app.get("/schema")
def get_schema():
    try:
        import schemas
        # Return class names to allow UI viewers
        return {
            "models": [
                "Users",
                "Planttemplates",
                "Userplants",
                "Actions",
                "Sensordata",
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/")
def root():
    return {"message": "Digital Plant Growth & Care System API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -------- Users ---------
@app.get("/api/users/demo")
def get_or_create_demo_user():
    users = db["users"]
    doc = users.find_one({"email": "demo@plants.app"})
    if not doc:
        user = {
            "name": "Demo Gardener",
            "email": "demo@plants.app",
            "xp": 0,
            "level": 1,
            "streak": 0,
            "badges": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        inserted = users.insert_one(user)
        doc = users.find_one({"_id": inserted.inserted_id})
    return serialize(doc)


# -------- Plant Templates ---------
class TemplateIn(BaseModel):
    template_name: str
    scientific_name: Optional[str] = None
    ideal_moisture: int
    ideal_light: int
    ideal_temperature: int = 24
    growth_days: int = 120
    instructions: Optional[str] = None
    example_images: List[str] = []


@app.get("/api/templates")
def list_templates():
    items = [serialize(x) for x in db["planttemplates"].find({}).limit(100)]
    return items


@app.post("/api/templates")
def create_template(t: TemplateIn):
    tid = create_document("planttemplates", t.model_dump())
    return {"_id": tid}


@app.post("/api/templates/seed")
def seed_templates():
    col = db["planttemplates"]
    if col.count_documents({}) > 0:
        return {"status": "ok", "message": "Templates already seeded"}
    seeds = [
        {
            "template_name": "Rose",
            "scientific_name": "Rosa",
            "ideal_moisture": 60,
            "ideal_light": 70,
            "ideal_temperature": 22,
            "growth_days": 180,
            "instructions": "Water when top soil is dry. Needs bright light.",
            "example_images": [],
        },
        {
            "template_name": "Money Plant",
            "scientific_name": "Epipremnum aureum",
            "ideal_moisture": 55,
            "ideal_light": 50,
            "ideal_temperature": 24,
            "growth_days": 160,
            "instructions": "Tolerates low light. Keep soil slightly moist.",
            "example_images": [],
        },
        {
            "template_name": "Ficus",
            "scientific_name": "Ficus benjamina",
            "ideal_moisture": 50,
            "ideal_light": 60,
            "ideal_temperature": 25,
            "growth_days": 220,
            "instructions": "Bright indirect light. Let soil dry slightly.",
            "example_images": [],
        },
        {
            "template_name": "Aloe Vera",
            "scientific_name": "Aloe barbadensis",
            "ideal_moisture": 30,
            "ideal_light": 80,
            "ideal_temperature": 26,
            "growth_days": 240,
            "instructions": "Succulent; water sparingly. Needs strong light.",
            "example_images": [],
        },
    ]
    for s in seeds:
        create_document("planttemplates", s)
    return {"status": "ok", "count": len(seeds)}


# -------- User Plants ---------
class PlantCreate(BaseModel):
    user_id: str
    template_id: str
    nickname: str


STAGE_THRESHOLDS = {
    "seed": 0,
    "sprout": 100,
    "juvenile": 250,
    "mature": 500,
}


def compute_health(plant: dict, template: dict) -> int:
    # Deviation from ideals
    dev_m = abs((plant.get("hydration", 0)) - template.get("ideal_moisture", 50))
    dev_l = abs((plant.get("sunlight", 0)) - template.get("ideal_light", 50))
    dev_n = abs((plant.get("nutrition", 0)) - 60)  # Assume ideal nutrition 60
    avg_dev = (dev_m + dev_l + dev_n) / 3.0
    score = 100 - avg_dev
    return int(clamp(score))


def apply_decay(plant: dict):
    plant["hydration"] = int(clamp(plant.get("hydration", 0) - 5))
    plant["nutrition"] = int(clamp(plant.get("nutrition", 0) - 2))
    plant["sunlight"] = int(clamp(round(plant.get("sunlight", 0) * 0.95)))


def apply_growth(plant: dict, template: dict):
    if plant.get("health_score", 0) > 70:
        plant["growth_points"] = plant.get("growth_points", 0) + 10
    gp = plant.get("growth_points", 0)
    stage = plant.get("stage", "seed")
    if gp >= STAGE_THRESHOLDS["mature"]:
        stage = "mature"
    elif gp >= STAGE_THRESHOLDS["juvenile"]:
        stage = "juvenile"
    elif gp >= STAGE_THRESHOLDS["sprout"]:
        stage = "sprout"
    else:
        stage = "seed"
    plant["stage"] = stage


@app.post("/api/plants")
def create_user_plant(payload: PlantCreate):
    user = db["users"].find_one({"_id": oid(payload.user_id)})
    template = db["planttemplates"].find_one({"_id": oid(payload.template_id)})
    if not user or not template:
        return JSONResponse({"error": "Invalid user or template"}, status_code=400)
    plant_doc = {
        "owner": str(user["_id"]),
        "template": str(template["_id"]),
        "nickname": payload.nickname,
        "planted_on": datetime.now(timezone.utc),
        "growth_points": 0,
        "hydration": 50,
        "nutrition": 50,
        "sunlight": 50,
        "health_score": 100,
        "stage": "seed",
        "last_action_date": None,
        "action_log": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    pid = db["userplants"].insert_one(plant_doc).inserted_id
    return {"_id": str(pid)}


@app.get("/api/plants")
def list_user_plants(user_id: str):
    items = [serialize(x) for x in db["userplants"].find({"owner": user_id}).limit(200)]
    return items


@app.get("/api/plants/{plant_id}")
def get_plant(plant_id: str):
    doc = db["userplants"].find_one({"_id": oid(plant_id)})
    if not doc:
        return JSONResponse({"error": "Not found"}, status_code=404)
    template = db["planttemplates"].find_one({"_id": oid(doc["template"])}) if doc.get("template") else None
    result = serialize(doc)
    result["template_data"] = serialize(template) if template else None
    return result


class CareAction(BaseModel):
    type: str  # water|fertilize|sunlight_add|trim|repot


@app.post("/api/plants/{plant_id}/care")
def care_action(plant_id: str, action: CareAction):
    plant = db["userplants"].find_one({"_id": oid(plant_id)})
    if not plant:
        return JSONResponse({"error": "Plant not found"}, status_code=404)
    template = db["planttemplates"].find_one({"_id": oid(plant["template"])}) if plant.get("template") else {}

    # Apply decay before action to simulate time passage
    apply_decay(plant)

    xp_reward = 0
    if action.type == "water":
        plant["hydration"] = int(clamp(plant.get("hydration", 0) + 20))
        xp_reward = 5
    elif action.type == "fertilize":
        plant["nutrition"] = int(clamp(plant.get("nutrition", 0) + 15))
        xp_reward = 7
    elif action.type == "sunlight_add":
        plant["sunlight"] = int(clamp(plant.get("sunlight", 0) + 10))
        xp_reward = 4
    elif action.type == "trim":
        plant["health_score"] = int(clamp(plant.get("health_score", 0) + 5))
        xp_reward = 6
    elif action.type == "repot":
        plant["health_score"] = int(clamp(plant.get("health_score", 0) + 10))
        xp_reward = 10
    else:
        return JSONResponse({"error": "Unknown action"}, status_code=400)

    # Update health and growth
    plant["health_score"] = compute_health(plant, template)
    apply_growth(plant, template)

    # Log action
    log_entry = {
        "type": action.type,
        "value": 1,
        "xp_reward": xp_reward,
        "date": datetime.now(timezone.utc),
    }
    plant.setdefault("action_log", []).insert(0, log_entry)
    plant["last_action_date"] = datetime.now(timezone.utc)
    plant["updated_at"] = datetime.now(timezone.utc)

    # Persist
    db["userplants"].update_one({"_id": oid(plant_id)}, {"$set": plant})

    # Add XP to user
    db["users"].update_one({"_id": oid(plant["owner"])}, {"$inc": {"xp": xp_reward}})

    return get_plant(plant_id)


@app.post("/api/growth/run")
def run_growth(user_id: str):
    plants = list(db["userplants"].find({"owner": user_id}))
    updated = 0
    for p in plants:
        template = db["planttemplates"].find_one({"_id": oid(p["template"])}) if p.get("template") else {}
        apply_decay(p)
        p["health_score"] = compute_health(p, template)
        apply_growth(p, template)
        p["updated_at"] = datetime.now(timezone.utc)
        db["userplants"].update_one({"_id": p["_id"]}, {"$set": p})
        updated += 1
    return {"updated": updated}


# -------- AI Features (mocked but structured) ---------
class IdentifyIn(BaseModel):
    image_url: Optional[str] = None


@app.post("/api/ai/identify")
def ai_identify(body: IdentifyIn):
    # Simple keyword-based mock
    url = (body.image_url or "").lower()
    species = "Unknown"
    guide = "General care: bright indirect light, water when top inch is dry."
    if "rose" in url:
        species = "Rose"
        guide = "Full sun, water regularly, fertilize during growing season."
    elif "aloe" in url:
        species = "Aloe Vera"
        guide = "Bright light, water sparingly, allow soil to dry out."
    elif "ficus" in url:
        species = "Ficus"
        guide = "Bright indirect light, keep soil lightly moist."
    elif "money" in url or "pothos" in url:
        species = "Money Plant (Pothos)"
        guide = "Low to bright light, water when soil is half dry."
    return {"species": species, "confidence": 0.72 if species != "Unknown" else 0.4, "care_guide": guide}


class DiseaseIn(BaseModel):
    image_url: Optional[str] = None


@app.post("/api/ai/disease")
def ai_disease(body: DiseaseIn):
    url = (body.image_url or "").lower()
    if "spot" in url or "brown" in url:
        return {"disease": "Leaf Spot", "severity": "moderate", "treatment": "Remove affected leaves, improve airflow, reduce overhead watering."}
    if "mold" in url or "powder" in url:
        return {"disease": "Powdery Mildew", "severity": "high", "treatment": "Apply fungicide, increase light, reduce humidity."}
    return {"disease": "Unknown", "severity": "low", "treatment": "Monitor plant, ensure proper care and hygiene."}


class ChatIn(BaseModel):
    plant_id: str
    question: Optional[str] = None


@app.post("/api/ai/chat")
def ai_chat(body: ChatIn):
    plant = db["userplants"].find_one({"_id": oid(body.plant_id)})
    if not plant:
        return {"answer": "I couldn't find that plant."}
    tmpl = db["planttemplates"].find_one({"_id": oid(plant["template"])}) if plant.get("template") else {}
    tips = []
    if plant.get("hydration", 0) < tmpl.get("ideal_moisture", 50) - 10:
        tips.append("Your plant looks thirsty. Consider watering it.")
    if plant.get("nutrition", 0) < 50:
        tips.append("A small dose of fertilizer can boost growth.")
    if plant.get("sunlight", 0) < tmpl.get("ideal_light", 60) - 10:
        tips.append("Move it to a brighter spot for more light.")
    if plant.get("health_score", 100) < 70:
        tips.append("Overall health is low; adjust watering, light, and nutrition.")
    if not tips:
        tips.append("Your plant is doing great! Keep up the consistent care.")
    return {"answer": " ".join(tips)}


# -------- IoT Sensor Ingest ---------
class SensorIn(BaseModel):
    plant_id: str
    moisture: Optional[float] = None
    temp: Optional[float] = None
    light: Optional[float] = None
    humidity: Optional[float] = None


@app.post("/api/iot/sensor")
def ingest_sensor(data: SensorIn):
    plant = db["userplants"].find_one({"_id": oid(data.plant_id)})
    if not plant:
        return JSONResponse({"error": "Plant not found"}, status_code=404)
    tmpl = db["planttemplates"].find_one({"_id": oid(plant["template"])}) if plant.get("template") else {}

    # Map sensor to metrics (simple normalization / heuristics)
    if data.moisture is not None:
        plant["hydration"] = int(clamp(data.moisture))
    if data.light is not None:
        normalized_light = clamp((data.light / 1000.0) * 100)  # assuming sensor 0-1000 lux scale sample
        plant["sunlight"] = int(normalized_light)
    # temp/humidity could influence health
    plant["health_score"] = compute_health(plant, tmpl)
    apply_growth(plant, tmpl)
    plant["updated_at"] = datetime.now(timezone.utc)
    db["userplants"].update_one({"_id": oid(data.plant_id)}, {"$set": plant})

    # Store raw sensor packet
    sensor_doc = {
        "plant": data.plant_id,
        "moisture": data.moisture,
        "temperature": data.temp,
        "humidity": data.humidity,
        "light": data.light,
        "timestamp": datetime.now(timezone.utc),
    }
    db["sensordata"].insert_one(sensor_doc)

    return get_plant(data.plant_id)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
