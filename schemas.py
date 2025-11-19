"""
Database Schemas for Digital Plant Growth & Care System

Each Pydantic model corresponds to a MongoDB collection. The collection name is the lowercase
of the class name.
"""
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# Users
class Users(BaseModel):
    name: str
    email: str
    xp: int = 0
    level: int = 1
    streak: int = 0
    badges: List[str] = Field(default_factory=list)

# PlantTemplates (preloaded species)
class Planttemplates(BaseModel):
    template_name: str
    scientific_name: Optional[str] = None
    ideal_moisture: int = Field(ge=0, le=100)
    ideal_light: int = Field(ge=0, le=100)
    ideal_temperature: int = Field(ge=0, le=60)
    growth_days: int = Field(ge=1, le=3650)
    instructions: Optional[str] = None
    example_images: List[str] = Field(default_factory=list)

# UserPlants
class Userplants(BaseModel):
    owner: str = Field(..., description="User id")
    template: str = Field(..., description="Plant template id")
    nickname: str
    planted_on: datetime
    growth_points: int = 0
    hydration: int = Field(0, ge=0, le=100)
    nutrition: int = Field(0, ge=0, le=100)
    sunlight: int = Field(0, ge=0, le=100)
    health_score: int = Field(100, ge=0, le=100)
    stage: str = Field("seed", description="seed|sprout|juvenile|mature")
    last_action_date: Optional[datetime] = None
    action_log: List[dict] = Field(default_factory=list)

# Actions
class Actions(BaseModel):
    plant: str
    type: str = Field(..., description="water|fertilize|trim|repot|sunlight_add")
    value: int
    xp_reward: int = 0
    date: datetime

# SensorData (future IoT)
class Sensordata(BaseModel):
    plant: str
    moisture: Optional[float] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    light: Optional[float] = None
    timestamp: datetime
