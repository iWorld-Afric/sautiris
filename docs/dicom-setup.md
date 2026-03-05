# DICOM Setup

SautiRIS provides three DICOM SCP (Service Class Provider) services for scanner integration:

1. **Modality Worklist (MWL) SCP** -- Serves scheduled procedures to modalities
2. **MPPS SCP** -- Receives Modality Performed Procedure Step notifications
3. **C-STORE SCP** -- Receives DICOM instances from modalities

## Configuration

```env
# MWL SCP
SAUTIRIS_DICOM_MWL_PORT=11112
SAUTIRIS_DICOM_MWL_AE_TITLE=SAUTIRIS_MWL

# MPPS SCP
SAUTIRIS_DICOM_MPPS_PORT=11113
SAUTIRIS_DICOM_MPPS_AE_TITLE=SAUTIRIS_MPPS

# C-STORE SCP
SAUTIRIS_DICOM_STORE_PORT=11114
SAUTIRIS_DICOM_STORE_AE_TITLE=SAUTIRIS_STORE
```

## Modality Worklist

The MWL SCP responds to C-FIND queries with scheduled procedures from SautiRIS orders.

### Scanner Configuration

Configure your scanner/modality to query the MWL SCP:

| Setting | Value |
|---------|-------|
| Remote AE Title | `SAUTIRIS_MWL` |
| Remote Host | IP of SautiRIS server |
| Remote Port | `11112` |

### Workflow

1. Create an order in SautiRIS (`POST /api/v1/orders`)
2. Schedule the order (`POST /api/v1/orders/{id}/schedule`)
3. Scanner queries MWL and receives the scheduled procedure
4. Technologist selects the patient and starts the exam

### Supported Query Keys

- Patient Name, Patient ID
- Accession Number
- Scheduled Procedure Step Start Date/Time
- Modality
- Scheduled Station AE Title

## MPPS (Modality Performed Procedure Step)

The MPPS SCP receives N-CREATE and N-SET messages from modalities to track exam progress.

### Scanner Configuration

| Setting | Value |
|---------|-------|
| Remote AE Title | `SAUTIRIS_MPPS` |
| Remote Host | IP of SautiRIS server |
| Remote Port | `11113` |

### Workflow

1. Scanner sends N-CREATE when exam starts (MPPS IN PROGRESS)
2. SautiRIS updates the worklist item status to IN_PROGRESS
3. Scanner sends N-SET when exam completes (MPPS COMPLETED/DISCONTINUED)
4. SautiRIS updates the worklist item accordingly

## PACS Integration

SautiRIS integrates with PACS servers for image storage and retrieval.

### Orthanc

```env
SAUTIRIS_PACS_TYPE=orthanc
SAUTIRIS_ORTHANC_BASE_URL=http://localhost:8042
SAUTIRIS_ORTHANC_DICOMWEB_ROOT=/dicom-web
SAUTIRIS_ORTHANC_USERNAME=orthanc
SAUTIRIS_ORTHANC_PASSWORD=orthanc
```

### DCM4CHEE

```env
SAUTIRIS_PACS_TYPE=dcm4chee
# DCM4CHEE adapter provides DICOMweb access via its REST API
```

## Viewer Integration

### OHIF Viewer

```env
SAUTIRIS_VIEWER_TYPE=ohif
SAUTIRIS_OHIF_BASE_URL=http://localhost:3000
SAUTIRIS_OHIF_DICOMWEB_DATASOURCE=default
```

SautiRIS generates deep-link URLs for studies:

```
http://localhost:3000/viewer?StudyInstanceUIDs=1.2.3.4.5
```

## Testing DICOM Connectivity

Use `findscu` (from DCMTK) to test MWL:

```bash
findscu -v -S -k "0008,0050=" -k "0010,0010=" \
  -k "0040,0100" \
  localhost 11112 -aet SCANNER -aec SAUTIRIS_MWL
```

Use `storescu` to test C-STORE:

```bash
storescu -v localhost 11114 -aet SCANNER -aec SAUTIRIS_STORE test.dcm
```

## Network Requirements

| Service | Port | Protocol | Direction |
|---------|------|----------|-----------|
| MWL SCP | 11112 | DICOM (TCP) | Inbound from modalities |
| MPPS SCP | 11113 | DICOM (TCP) | Inbound from modalities |
| C-STORE SCP | 11114 | DICOM (TCP) | Inbound from modalities |
| Orthanc REST | 8042 | HTTP | Outbound to PACS |
| OHIF Viewer | 3000 | HTTP | Frontend access |
