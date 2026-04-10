from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql://zachdb:zachdb@zachdb-postgres.zachdb.svc.cluster.local:5432/zachdb"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_api_key: str = "sk-madge-litellm-2026"
    llm_model: str = "madge-brain"
    llm_api_base: str = "http://100.89.229.85:4000/v1"
    mm_webhook_url: str = ""
    discord_webhook_url: str = ""
    gog_host: str = "macmini"
    base_url: str = "http://schedule.k3s.local"
    nbt_schema: str = "nbt"

    # Qwen smart classifier (Alibaba Cloud Coding Plan)
    qwen_api_key: str = ""
    qwen_api_base: str = "https://coding-intl.dashscope.aliyuncs.com/v1"
    qwen_model: str = "qwen3.5-plus"
    qwen_enabled: bool = True  # set False to skip AI layer entirely

    class Config:
        env_prefix = "NBT_"

settings = Settings()
