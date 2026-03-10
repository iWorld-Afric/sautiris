"""SautiRIS configuration via Pydantic Settings."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when the application configuration is invalid."""


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
    auth_provider: Literal["keycloak", "oauth2", "apikey"] = "keycloak"
    keycloak_server_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_jwks_url: str = ""
    oauth2_jwks_url: str = ""
    oauth2_issuer: str = ""
    oauth2_audience: str = ""
    api_key_header: str = "X-API-Key"

    # --- JWKS Cache ---
    jwks_cache_ttl: int = 600  # seconds; 0 = never cache
    jwks_key_miss_refetch_interval: int = 60  # min seconds between forced refetches

    # --- PACS ---
    pacs_type: Literal["orthanc", "dcm4chee", "custom"] = "orthanc"
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
    # --- DICOM Security (Issue #17) ---
    dicom_bind_address: str = "127.0.0.1"
    dicom_ae_whitelist: list[str] | None = None  # None = allow all
    dicom_max_connections_per_ip: int = 10
    dicom_ip_rate_limit_per_minute: int = 60
    # #21: dicom_tls_enabled gates build_dicom_ssl_context() in dicom/security.py.
    # When True, dicom_tls_ca_cert/cert/key must also be set.  Call
    # build_dicom_ssl_context(settings) at server startup to apply TLS.
    dicom_tls_enabled: bool = False
    dicom_tls_ca_cert: str = ""
    dicom_tls_cert: str = ""
    dicom_tls_key: str = ""

    # --- DICOM SOP class & transfer syntax configurability (Issue #25) ---
    # Empty list = use defaults from sautiris.dicom.constants.
    # Provide explicit UIDs to restrict or extend the supported set.
    dicom_storage_sop_classes: list[str] = []
    dicom_transfer_syntaxes: list[str] = []

    # --- FHIR ---
    fhir_base_url: str = ""
    fhir_auth_token: str = ""

    # --- HL7v2 ---
    hl7v2_mllp_port: int = 2575

    # --- Viewer ---
    viewer_type: Literal["ohif", "custom"] = "ohif"
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
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"

    # --- CORS (issue #4) ---
    # BREAKING: default changed from ["*"] to [] — operators must configure explicitly.
    cors_origins: list[str] = []
    cors_allow_credentials: bool = False
    cors_allow_methods: list[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    # #3: X-Tenant-ID, X-API-Key, and X-Correlation-ID are used in deps/middleware
    cors_allow_headers: list[str] = [
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-Tenant-ID",
        "X-API-Key",
        "X-Correlation-ID",
    ]

    # --- Encryption (issue #6) ---
    # Set to a Fernet key: Fernet.generate_key().decode()
    # Required in production; empty = no encryption (development only).
    encryption_key: str = ""
    environment: Literal["development", "staging", "production"] = "development"

    # --- Rate limiting (issue #40) ---
    rate_limit_enabled: bool = True
    rate_limit_general: str = "100/minute"
    rate_limit_auth_endpoints: str = "10/minute"
    rate_limit_apikey_create: str = "5/minute"
    rate_limit_trusted_ips: list[str] = []

    # --- Audit (Issue #22, #65) ---
    # audit_log_reads: whether READ (GET) operations are written to the audit log.
    # Disable only in high-throughput environments where read-audit is not required.
    audit_log_reads: bool = True
    # audit_log_retention_days: how long audit records are kept (for purge jobs).
    # Default 365 days satisfies most HIPAA retention requirements.
    audit_log_retention_days: int = 365

    # --- Tenant ---
    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    tenant_header: str = "X-Tenant-ID"
    tenant_jwt_claim: str = "tenant_id"

    def validate_security(self) -> None:
        """Raise ConfigurationError for invalid security settings.

        Call this during application startup.  A ``@model_validator(mode='after')``
        would auto-run this on construction, but existing tests create invalid
        settings objects and call this method explicitly — converting would break
        those tests.  A future refactor can migrate tests and add the decorator.
        """
        if "*" in self.cors_origins and self.cors_allow_credentials:
            raise ConfigurationError(
                "CORS wildcard origin ('*') with cors_allow_credentials=True is forbidden. "
                "Set cors_origins to specific domains instead."
            )
        if self.environment == "production" and not self.encryption_key:
            raise ConfigurationError(
                "SAUTIRIS_ENCRYPTION_KEY must be set in production. "
                'Generate one with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
