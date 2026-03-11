# DICOM Conformance Statement — SautiRIS v1.0

**Conformance Statement for**: SautiRIS Radiology Information System  
**Version**: 1.0.0  
**Standard**: DICOM PS3.2 (Conformance)  
**Date**: 2026-03-06

---

## 1. Introduction

### 1.1 Purpose

This document is the DICOM conformance statement for SautiRIS, an open-source
Radiology Information System (RIS). It describes the DICOM services supported,
the SOP Classes accepted or provided, and the transfer syntaxes negotiated.

### 1.2 Intended Audience

This statement is intended for system integrators, PACS administrators, and
modality vendors who wish to integrate with SautiRIS.

### 1.3 Revision History

| Version | Date       | Change                          |
|---------|------------|---------------------------------|
| 1.0.0   | 2026-03-06 | Initial conformance statement   |

---

## 2. Implementation Information

### 2.1 Manufacturer Identification

| Parameter                | Value                                               |
|--------------------------|-----------------------------------------------------|
| **Manufacturer**         | iWorld-Afric                                        |
| **Product Name**         | SautiRIS                                            |
| **Product Version**      | 1.0.0                                               |
| **License**              | Open-source (see repository LICENSE file)           |
| **Source Repository**    | https://github.com/iWorld-Afric/sautiris            |
| **Issue Tracker / Contact** | https://github.com/iWorld-Afric/sautiris/issues |

### 2.2 DICOM Implementation Parameters

| Parameter          | Value                           |
|--------------------|---------------------------------|
| Implementation UID | `1.2.826.0.1.3680043.9.7539.1` |
| Implementation Version | `SAUTIRIS_100`            |
| AE Title (MWL SCP) | `SAUTIRIS_MWL` (configurable)  |
| AE Title (MPPS SCP)| `SAUTIRIS_MPPS` (configurable) |
| AE Title (Store SCP)| `SAUTIRIS_STORE` (configurable)|
| Max PDU Length     | 65536 bytes (default pynetdicom)|

---

## 3. Networking

### 3.1 TCP/IP Stack

SautiRIS uses standard TCP/IP networking via pynetdicom.

| Parameter     | Value                 |
|---------------|-----------------------|
| IP Version    | IPv4 and IPv6         |
| Transport     | TCP                   |
| Default Bind  | `127.0.0.1` (localhost; configure `SAUTIRIS_DICOM_BIND_ADDRESS`) |

> **Security Note**: By default SautiRIS binds DICOM SCPs to `127.0.0.1` (loopback only).
> To expose on network interfaces, set `SAUTIRIS_DICOM_BIND_ADDRESS=0.0.0.0` and enable
> TLS (`SAUTIRIS_DICOM_TLS_ENABLED=true`).

### 3.2 Optional TLS

SautiRIS supports TLS for DICOM associations when configured:

| Setting                      | Description                      |
|------------------------------|----------------------------------|
| `SAUTIRIS_DICOM_TLS_ENABLED` | Enable TLS (default: `false`)   |
| `SAUTIRIS_DICOM_TLS_CA_CERT` | Path to CA certificate file      |
| `SAUTIRIS_DICOM_TLS_CERT`    | Path to server certificate file  |
| `SAUTIRIS_DICOM_TLS_KEY`     | Path to server private key file  |

### 3.3 Association Security

SautiRIS enforces the following security controls on incoming associations:

| Control                | Setting                                  | Default   |
|------------------------|------------------------------------------|-----------|
| AE Title Whitelist     | `SAUTIRIS_DICOM_AE_WHITELIST`           | Allow all |
| Max Connections per IP | `SAUTIRIS_DICOM_MAX_CONNECTIONS_PER_IP` | 10        |
| Rate Limit (req/min)   | `SAUTIRIS_DICOM_IP_RATE_LIMIT_PER_MINUTE` | 60     |

AE title patterns support shell-style wildcards (e.g., `CT_SCANNER_*`).

---

## 4. Implementation Model

### 4.1 Application Data Flow

```
Modality ─── C-FIND ──► MWL SCP  ──► WorklistRepository ──► PostgreSQL
Modality ─── N-CREATE/N-SET ──► MPPS SCP ──► MPPSRepository ──► PostgreSQL
Modality ─── C-STORE ──► Store SCP ──► PACSAdapter (STOW-RS) ──► PACS
                                    └──► RDSR Pipeline ──► DoseRecord
```

### 4.2 Processes

| Process      | AE Title         | Port  | Protocol         |
|--------------|------------------|-------|------------------|
| MWL SCP      | `SAUTIRIS_MWL`   | 11112 | DICOM C-FIND     |
| MPPS SCP     | `SAUTIRIS_MPPS`  | 11113 | DICOM N-CREATE / N-SET |
| C-STORE SCP  | `SAUTIRIS_STORE` | 11114 | DICOM C-STORE    |

All ports are configurable via environment variables (`SAUTIRIS_DICOM_*_PORT`).

---

## 5. AE Specifications

### 5.1 Modality Worklist SCP (`SAUTIRIS_MWL`)

**Role**: Service Class Provider (SCP)

#### 5.1.1 Supported SOP Classes

| SOP Class                                    | SOP Class UID              |
|----------------------------------------------|----------------------------|
| Modality Worklist Information Model – FIND   | `1.2.840.10008.5.1.4.31`  |

#### 5.1.2 Transfer Syntaxes

| Transfer Syntax                   | UID                        |
|-----------------------------------|----------------------------|
| Explicit VR Little Endian         | `1.2.840.10008.1.2.1`     |
| Implicit VR Little Endian         | `1.2.840.10008.1.2`       |
| JPEG Baseline (Process 1)         | `1.2.840.10008.1.2.4.50`  |
| JPEG Lossless (Process 14 SV1)    | `1.2.840.10008.1.2.4.70`  |
| JPEG 2000 Lossless Only           | `1.2.840.10008.1.2.4.90`  |
| JPEG 2000                         | `1.2.840.10008.1.2.4.91`  |
| RLE Lossless                      | `1.2.840.10008.1.2.5`     |
| Deflated Explicit VR Little Endian| `1.2.840.10008.1.2.1.99`  |

#### 5.1.3 MWL Query Attributes

The MWL SCP supports C-FIND queries matching on the following attributes
with universal matching semantics (empty value = match all):

| Attribute                          | Tag        | Match Type       |
|------------------------------------|------------|------------------|
| PatientID                          | (0010,0020)| Universal / Exact|
| PatientName                        | (0010,0010)| Universal / Exact / Wildcard (*,?)|
| AccessionNumber                    | (0008,0050)| Universal / Exact|
| RequestedProcedureID               | (0040,1001)| Universal / Exact|
| Modality                           | (0008,0060)| Universal / Exact|
| ScheduledStationAETitle            | (0040,0001)| Universal / Exact|
| ScheduledProcedureStepStartDate    | (0040,0002)| Universal / Range|
| ScheduledProcedureStepStatus       | (0040,0020)| Universal / Exact|

#### 5.1.4 MWL Response Attributes

Each response dataset includes the following attributes (DICOM PS3.4 Annex K):

**Type 1 (Mandatory):**
- StudyInstanceUID (0020,000D) — generated per worklist item if absent

**Type 1C:**
- ReferencedStudySequence (0008,1110)
- RequestedProcedureCodeSequence (0032,1064)

**Type 2 (Required, may be empty):**
- PatientName, PatientID, PatientBirthDate, PatientSex
- PatientWeight, MedicalAlerts, Allergies, PregnancyStatus
- IssuerOfPatientID (0010,0021), AdmissionID (0038,0010)
- ReferencedPatientSequence (0008,1120)
- AccessionNumber, ReferringPhysicianName
- RequestedProcedureID, RequestedProcedureDescription
- RequestedProcedurePriority
- StudyID, StudyDate, StudyTime
- RequestAttributesSequence (0040,0275)
- ScheduledProcedureStepSequence (0040,0100) containing:
  - Modality, ScheduledStationAETitle
  - ScheduledProcedureStepStartDate/Time
  - ScheduledProcedureStepID, ScheduledProcedureStepDescription
  - ScheduledProcedureStepStatus
  - ScheduledPerformingPhysicianName
  - ScheduledProtocolCodeSequence (0040,0008)

**SpecificCharacterSet**: `ISO_IR 192` (UTF-8) is set on all outbound datasets.

---

### 5.2 MPPS SCP (`SAUTIRIS_MPPS`)

**Role**: Service Class Provider (SCP)

#### 5.2.1 Supported SOP Classes

| SOP Class                                             | SOP Class UID              |
|-------------------------------------------------------|----------------------------|
| Modality Performed Procedure Step (N-CREATE / N-SET)  | `1.2.840.10008.3.1.2.3.3` |

#### 5.2.2 Transfer Syntaxes

Same 8 transfer syntaxes as MWL SCP (see Section 5.1.2).

#### 5.2.3 MPPS State Machine

```
     [N-CREATE with status = "IN PROGRESS"]
              │
              ▼
         IN PROGRESS ──── N-SET ──→ COMPLETED   (terminal)
                     └─── N-SET ──→ DISCONTINUED (terminal)

Constraints:
  - N-CREATE MUST set PerformedProcedureStepStatus = "IN PROGRESS"
    (any other value → 0x0110 Attribute Value Out of Range)
  - Duplicate N-CREATE for existing SOP Instance UID → 0x0111
  - N-SET from terminal state → 0x0110
  - N-SET with target status other than COMPLETED/DISCONTINUED → 0x0110

Type 1 Attribute Validation (PS3.4 F.7.2):
  - N-CREATE requires: PerformedProcedureStepID, PerformedStationAETitle,
    PerformedProcedureStepStartDate, PerformedProcedureStepStartTime
  - N-SET to COMPLETED requires: PerformedProcedureStepEndDate,
    PerformedProcedureStepEndTime
  - N-SET to DISCONTINUED requires: PerformedProcedureStepEndDate,
    PerformedProcedureStepEndTime, PerformedProcedureStepDiscontinuationReasonCodeSequence
  - Missing required attributes → 0x0110

Persistence:
  - MPPS instances are tracked in-memory for fast state lookups
  - DB persistence via callback (mpps_instances table)
  - On restart, active instances can be preloaded via preload_active_instances()
```

MPPS instances are persisted to the `mpps_instances` table (PostgreSQL).

---

### 5.3 C-STORE SCP (`SAUTIRIS_STORE`)

**Role**: Service Class Provider (SCP)

#### 5.3.1 Supported SOP Classes (29 classes)

| SOP Class                                   | SOP Class UID                     |
|---------------------------------------------|-----------------------------------|
| CT Image Storage                            | `1.2.840.10008.5.1.4.1.1.2`      |
| MR Image Storage                            | `1.2.840.10008.5.1.4.1.1.4`      |
| Computed Radiography Image Storage          | `1.2.840.10008.5.1.4.1.1.1`      |
| Digital X-Ray Image Storage                 | `1.2.840.10008.5.1.4.1.1.1.1`    |
| Ultrasound Image Storage                    | `1.2.840.10008.5.1.4.1.1.6.1`    |
| Secondary Capture Image Storage             | `1.2.840.10008.5.1.4.1.1.7`      |
| Enhanced CT Image Storage                   | `1.2.840.10008.5.1.4.1.1.2.1`    |
| Enhanced MR Image Storage                   | `1.2.840.10008.5.1.4.1.1.4.1`    |
| Digital Mammography Image Storage           | `1.2.840.10008.5.1.4.1.1.1.2`    |
| Digital Mammography Presentation State      | `1.2.840.10008.5.1.4.1.1.1.2.1`  |
| Breast Tomosynthesis Image Storage          | `1.2.840.10008.5.1.4.1.1.13.1.3` |
| Nuclear Medicine Image Storage              | `1.2.840.10008.5.1.4.1.1.20`     |
| Positron Emission Tomography Image Storage  | `1.2.840.10008.5.1.4.1.1.128`    |
| X-Ray Angiographic Image Storage            | `1.2.840.10008.5.1.4.1.1.12.1`   |
| Enhanced X-Ray Angiographic Image Storage   | `1.2.840.10008.5.1.4.1.1.12.1.1` |
| X-Ray RF Image Storage                      | `1.2.840.10008.5.1.4.1.1.12.2`   |
| Basic Text SR Storage                       | `1.2.840.10008.5.1.4.1.1.88.11`  |
| Radiation Dose SR Storage (RDSR)            | `1.2.840.10008.5.1.4.1.1.88.67`  |
| Enhanced SR Storage                         | `1.2.840.10008.5.1.4.1.1.88.22`  |
| Comprehensive SR Storage                    | `1.2.840.10008.5.1.4.1.1.88.33`  |
| Key Object Selection Document Storage       | `1.2.840.10008.5.1.4.1.1.88.59`  |
| Encapsulated PDF Storage                    | `1.2.840.10008.5.1.4.1.1.104.1`  |
| Grayscale Softcopy Presentation State       | `1.2.840.10008.5.1.4.1.1.11.1`   |
| RT Image Storage                            | `1.2.840.10008.5.1.4.1.1.481.1`  |
| VL Endoscopic Image Storage                 | `1.2.840.10008.5.1.4.1.1.77.1.1` |
| Segmentation Storage                        | `1.2.840.10008.5.1.4.1.1.66.4`   |
| Ultrasound Multi-frame Image Storage        | `1.2.840.10008.5.1.4.1.1.3.1`    |
| MR Spectroscopy Storage                     | `1.2.840.10008.5.1.4.1.1.4.2`    |
| Enhanced MR Color Image Storage             | `1.2.840.10008.5.1.4.1.1.4.3`    |

#### 5.3.2 Transfer Syntaxes

Same 8 transfer syntaxes as MWL SCP (see Section 5.1.2).

#### 5.3.3 RDSR Routing

When a Radiation Dose SR (`1.2.840.10008.5.1.4.1.1.88.67`) is received,
it is automatically forwarded to the dose extraction pipeline (if configured)
in addition to the standard PACS forwarding path.

---

## 6. Communication Profiles

### 6.1 TCP/IP Stack

SautiRIS uses the standard pynetdicom TCP/IP stack with DICOM Upper Layer (DUL)
service provider per PS3.8.

### 6.2 Security Profiles

| Profile                       | Support |
|-------------------------------|---------|
| Basic TLS Secure Transport    | Optional (configurable) |
| AE Title Authentication       | Yes (whitelist-based)   |
| Connection Rate Limiting      | Yes (per-IP)            |

---

## 7. Configuration

### 7.1 Environment Variables

| Variable                              | Default             | Description               |
|---------------------------------------|---------------------|---------------------------|
| `SAUTIRIS_DICOM_MWL_PORT`            | `11112`             | MWL SCP listen port       |
| `SAUTIRIS_DICOM_MWL_AE_TITLE`        | `SAUTIRIS_MWL`      | MWL AE title              |
| `SAUTIRIS_DICOM_MPPS_PORT`           | `11113`             | MPPS SCP listen port      |
| `SAUTIRIS_DICOM_MPPS_AE_TITLE`       | `SAUTIRIS_MPPS`     | MPPS AE title             |
| `SAUTIRIS_DICOM_STORE_PORT`          | `11114`             | Store SCP listen port     |
| `SAUTIRIS_DICOM_STORE_AE_TITLE`      | `SAUTIRIS_STORE`    | Store AE title            |
| `SAUTIRIS_DICOM_BIND_ADDRESS`        | `127.0.0.1`         | Bind address (all SCPs)   |
| `SAUTIRIS_DICOM_AE_WHITELIST`        | `(unset = allow all)`| AE title whitelist       |
| `SAUTIRIS_DICOM_MAX_CONNECTIONS_PER_IP` | `10`            | Max concurrent per IP     |
| `SAUTIRIS_DICOM_IP_RATE_LIMIT_PER_MINUTE` | `60`        | Rate limit per IP/minute  |
| `SAUTIRIS_DICOM_TLS_ENABLED`         | `false`             | Enable TLS                |
| `SAUTIRIS_DICOM_TLS_CA_CERT`         | `""`                | CA cert path              |
| `SAUTIRIS_DICOM_TLS_CERT`            | `""`                | Server cert path          |
| `SAUTIRIS_DICOM_TLS_KEY`             | `""`                | Server key path           |
| `SAUTIRIS_ENABLE_DICOM_MWL`          | `true`              | Enable MWL SCP            |
| `SAUTIRIS_ENABLE_DICOM_MPPS`         | `true`              | Enable MPPS SCP           |

---

## 8. Multi-Tenancy Considerations

SautiRIS is designed as a multi-tenant RIS.  The following considerations
apply to DICOM operations in a multi-tenant deployment.

### 8.1 Tenant Isolation

Each tenant's worklist items, MPPS instances, and stored DICOM metadata are
stored in separate database rows tagged with a `tenant_id` column.  No
cross-tenant data leakage occurs at the application layer; queries are always
filtered by the active tenant context.

### 8.2 AE Title per Tenant

SautiRIS supports per-tenant AE title configuration.  Each tenant can be
assigned a unique AE title prefix so that modalities can route DICOM
associations to the correct tenant context.

| Setting                             | Description                                             |
|-------------------------------------|---------------------------------------------------------|
| `SAUTIRIS_DICOM_MWL_AE_TITLE`      | Default MWL AE title (applies to the default tenant)   |
| Per-tenant AE title overrides       | Configurable via the tenant administration API          |

### 8.3 Association-to-Tenant Mapping

Incoming DICOM associations are mapped to a tenant using the following
priority order:

1. The Called AE Title of the association, matched against per-tenant AE
   title configuration.
2. The `X-Tenant-ID` HTTP header (for DICOMweb / STOW-RS requests).
3. The default tenant (`SAUTIRIS_DEFAULT_TENANT_ID`) if no match is found.

> **Note**: In production, always configure explicit AE titles per tenant to
> avoid ambiguous tenant resolution.

### 8.4 DICOM Metadata Segregation

DICOM datasets forwarded to the PACS adapter are not modified with tenant
identifiers (to preserve standard DICOM compliance).  Tenant context is
maintained exclusively within the SautiRIS database and is not embedded in
DICOM datasets.

---

## 9. Limitations and Notes

1. **MWL Matching**: Universal (empty=all), exact, and wildcard (`*`, `?`) matching supported for PatientName. Fuzzy (phonetic) matching is not supported.
2. **C-MOVE**: Not implemented. PACS retrieval uses DICOMweb WADO-RS instead.
3. **C-GET**: Not implemented.
4. **Storage Commitment**: Not implemented in v1.0.
5. **MPPS Persistence**: Requires PostgreSQL; SQLite (test mode) supported via JSON fallback.
6. **Character Sets**: SautiRIS exclusively uses `ISO_IR 192` (UTF-8) for outbound datasets.
   Incoming datasets with other character sets are processed by pydicom's default handler.

---

*This conformance statement was generated per DICOM PS3.2 guidance.*
