"""SautiRIS configuration via Pydantic Settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SautiRISSettings(BaseSettings):
    """Central configuration for SautiRIS."""

    model_config = SettingsConfigDict(env_prefix="SAUTIRIS_", env_file=".env", extra="ignore")

    # --- Database ---
    database_url: str = "postgresql+asyncpg://localhost:5432/sautiris"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    auth_provider: str = "keycloak"  # keycloak | oauth2 | apikey
    keycloak_server_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_jwks_url: str = ""
    oauth2_jwks_url: str = ""
    oauth2_issuer: str = ""
    oauth2_audience: str = ""
    api_key_header: str = "X-API-Key"

    # --- PACS ---
    pacs_type: str = "orthanc"  # orthanc | dcm4chee | custom
    orthanc_base_url: str = "http://localhost:8042"
    orthanc_dicomweb_root: str = "/dicom-web"
    orthanc_username: str = ""
    orthanc_password: str = ""

    # --- DICOM ---
    dicom_mwl_port: int = 11112
    dicom_mwl_ae_title: str = "SAUTIRIS_MWL"
    dicom_mpps_port: int = 11113
    dicom_mpps_ae_title: str = "SAUTIRIS_MPPS"
    dicom_store_port: int = 11114
    dicom_store_ae_title: str = "SAUTIRIS_STORE"

    # --- FHIR ---
    fhir_base_url: str = ""
    fhir_auth_token: str = ""

    # --- HL7v2 ---
    hl7v2_mllp_port: int = 2575

    # --- Viewer ---
    viewer_type: str = "ohif"  # ohif | custom
    ohif_base_url: str = "http://localhost:3000"
    ohif_dicomweb_datasource: str = ""

    # --- Feature flags ---
    enable_dicom_mwl: bool = True
    enable_dicom_mpps: bool = True
    enable_fhir: bool = True
    enable_hl7v2: bool = False
    enable_ai: bool = False
    enable_viewer: bool = True
    enable_dose_tracking: bool = True
    enable_peer_review: bool = True
    enable_billing: bool = True

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1
    log_level: str = "info"
    cors_origins: list[str] = ["*"]

    # --- Tenant ---
    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    tenant_header: str = "X-Tenant-ID"
    tenant_jwt_claim: str = "tenant_id"
