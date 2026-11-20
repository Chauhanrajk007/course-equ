# Presidency University: Course Equivalence & Credit Mapping System
## Demonstration & Architecture Guide

---

## 1. Executive Summary & Purpose

The **Course Equivalence & Credit Mapping Engine** automates the academic equivalence process for Presidency University students who take a break in study and are re-admitted into a newer curriculum batch (e.g., admitting batch `2021-2025` re-admitted into `2024-2028` or `2025-2029`).

### Key Capabilities:
- **Instant Annexure-A PDF Generation:** Generates the official university-formatted Annexure-A report complete with Tables I through V and student signature blocks.
- **Strict Degree Credit Reconciliation:** Guaranteed $B + C + D + E + F = 160$ degree credits audit.
- **Dual-Path Architecture:** 
  1. *Deterministic Local Parser* (< 50ms) for digital files (`.docx`, `.xlsx`, `.csv`, `.pdf`).
  2. *Accelerated Vision OCR* (~2–4s) for scanned marksheets and camera photos.
  3. *Zero-AI Manual Entry* (< 0.1s) for offline curriculum selection.
- **Human-in-the-Loop Safeguards:** Every parsed course is confirmed on an editable preview screen before mapping, with manual override capabilities for academic advisors.

---

## 2. System Architecture & Data Flow

```
                                [ Student Documents ]
                                          |
       +----------------------------------+----------------------------------+
       |                                  |                                  |
 [ Digital Files ]              [ Photos / Scanned PDFs ]            [ Manual Entry ]
 (.docx, .xlsx, .csv, PDF)      (.png, .jpg, scanned PDF)            (/manual)
       |                                  |                                  |
       v                                  v                                  v
 [ Local Parsers ]              [ Vision AI Pipeline ]              [ PRC Database ]
 (pdfplumber, docx, openpyxl)   (Groq Qwen 3.8 / OpenRouter)        (Pre-fills courses)
 [ Execution: < 50ms ]          [ Multithreaded: ~2-5s ]            [ Execution: < 10ms ]
       |                                  |                                  |
       +----------------------------------+----------------------------------+
                                          |
                                          v
                              [ Check What Was Read ]
                            (Editable verification UI)
                                          |
                                          v
                            [ Course Equivalence Engine ]
                              (Rules & PRC Grid Mapping)
                                          |
                                          v
                            [ Review & Override Screen ]
                           (Tables I-V + 160 Credit Audit)
                                          |
                                          v
                           [ Official Annexure-A PDF ]
                            (ReportLab signed export)
```

---

## 3. The 3 Processing Pathways

| Feature | Pathway 1: Digital Documents | Pathway 2: Scanned Photos/PDFs | Pathway 3: Manual Entry |
|---|---|---|---|
| **Supported Inputs** | `.docx`, `.xlsx`, `.csv`, text `.pdf` | `.jpg`, `.png`, camera photos, scanned PDFs | Form input (`/manual`) |
| **Engine Used** | Python internal parsers | Groq `qwen/qwen3.8-27b` (fallback: OpenRouter) | Direct lookup from `prc_db.json` |
| **Processing Time** | **< 0.1 seconds** | **~2–5 seconds** (parallel 4 workers) | **< 0.05 seconds** |
| **External AI Gateway?** | ❌ No (100% offline) |  Yes (Groq Vision API) | ❌ No (100% offline) |
| **Credit/Balance Needed?**| ❌ No | ❌ Free API key on Groq | ❌ No |
| **Best Used For** | ERP marksheets, digital transcripts | Scanned hard copies, phone snapshots | Instant verification without files |

---

## 4. Academic Logic: Tables I to V & 160 Credit Audit

The engine follows official Presidency University academic regulations:

### **Table I: Mapped Courses & Transferred Credits ($B$)**
- Courses completed in the original curriculum that map to equivalent courses in the new curriculum.
- Earned credits are credited towards the new degree requirement.

### **Table II: Courses Not Cleared / Backlogs ($C$)**
- Courses where the student received an `F` grade or did not attend.
- Flagged to be completed under the new curriculum.

### **Table III: Grade Improvement Courses ($D$)**
- Completed courses where the student passed with minimum grade (`D`) and opts to re-register for grade improvement.

### **Table IV: Additional Mandatory Courses in New Batch ($E$)**
- New core courses introduced in the readmission batch's lower semesters that were absent in the student's original curriculum.

### **Table V: Surplus / Exempted Courses ($F$)**
- Courses completed in the old curriculum that have no equivalent in the new curriculum, or credit surpluses treated as open electives.

### **Degree Credit Reconciliation Formula**
$$\text{Total Degree Requirement} = B + C + D + E + F = 160\text{ Credits}$$
*The system alerts the committee if the total deviates from 160 credits before PDF issuance.*

---

## 5. Live Demonstration Script (Step-by-Step)

Follow this sequence for presentations or evaluation committees:

### **Demo 1: Instant Digital File Processing (< 1s)**
1. Open the application: `http://127.0.0.1:5000` (or your Render URL).
2. Set **Batch of Admission**: `2023-2027` (or student's batch).
3. Set **Batch of Readmission**: `2025-2029`.
4. Upload a digital document (e.g. `Chaitanya Reddy V_20231CAI0045.pdf` or `.docx`).
5. Click **Read report card**.
6. **Key Point to Highlight:** Notice the page transitions in **under 1 second**. Explain that digital files do not use AI, run 100% locally, and have zero credit cost.

### **Demo 2: Verifying & Editing Course Records**
1. On the **Check what was read** page, demonstrate how every course code, title, credits, and grade is editable.
2. Uncheck one course or edit a grade to show the human-in-the-loop verification safeguard.
3. Click **Map courses**.

### **Demo 3: Review, Manual Override & 160-Credit Balance**
1. Display the **Review the mapping** screen:
   - Point out **Table I** (Mapped courses).
   - Point out **Table IV** (Additional courses student must take in new batch).
   - Point out the **Summary card**: show the equation $B + C + D + E + F = 160$.
2. Demonstrate an override: select a dropdown mapping for any course and click **Save overrides**. Notice the credits immediately recalculate and reconcile to 160.

### **Demo 4: Scanned Photo / Image Processing**
1. Start a new case and upload a marksheet photo or clean scanned report card (`Kunduru_Harsha_Vardhan_Reddy_20221CAI0014_Report_Card.pdf`).
2. Show that the side-by-side view displays the original photo next to the transcribed courses for visual cross-checking.

### **Demo 5: Instant Fallback Mode (Zero-AI Manual Entry)**
1. Navigate to `http://127.0.0.1:5000/manual`.
2. Select batches and last completed semester (e.g. Semester 3).
3. Click **Load courses from curriculum**.
4. Show that all courses from semesters 1 to 3 are pre-populated automatically. Select passed courses and click **Map courses**.

### **Demo 6: Downloading Official Annexure-A PDF**
1. Click **Download Annexure A (PDF)**.
2. Open the downloaded PDF in the browser:
   - Official Presidency University header & emblem.
   - Clean tabular formatting for all Tables I–V.
   - Formal declaration statement and sign-off blocks (Dean, HOD, Academic Cell).

---

## 6. Deployment & Hosting Guide

### **A. Local Execution**
```powershell
# Navigate to workspace
cd "c:\Users\Chauhan Raj K\Desktop\course-equivalence"

# Run Flask server
python app.py
```
*Access at: `http://127.0.0.1:5000`*

### **B. Production on Render (Recommended)**
- **Repository:** `https://github.com/Chauhanrajk007/course-equ.git` (`master` branch)
- **Start Command:** `gunicorn --config gunicorn.conf.py app:app`
- **Dynamic Port Binding:** Handled automatically in `gunicorn.conf.py` (`0.0.0.0:$PORT`).
- **Environment Variables:**
  - `GROQ_API_KEY`: Groq vision API key.
  - `OPENROUTER_API_KEY`: OpenRouter API key (secondary fallback).
  - `COURSE_EQUIV_SECRET`: Flask secret key.

### **C. Why Render vs Vercel?**
- **Vercel:** Hard-caps request payload at **4.5 MB** (`413 FUNCTION_PAYLOAD_TOO_LARGE`). Scanned multi-page marksheets (6–18 MB) are rejected at the edge proxy.
- **Render:** Has no 4.5 MB payload limit, supports long-running background workers, and processes full multi-page document batches smoothly.

---

## 7. Frequently Asked Questions (FAQ)

**Q: Why was an upload taking 2 minutes earlier?**  
*A:* An earlier test upload contained a 31-page institutional package (including transfer certificates, circulars, fee slips) that was being compressed as heavy uncompressed PNGs and sent sequentially to an overloaded free gateway. With our updates:
1. Images are compressed to fast 1200px JPEGs (90% smaller).
2. Pages are processed concurrently across 4 worker threads.
3. Groq's high-speed LPU vision engine handles OCR in ~0.5s per page.

**Q: What happens if the internet is down or AI keys expire?**  
*A:* All digital formats (`.docx`, `.xlsx`, `.pdf`) and the manual entry system (`/manual`) run 100% locally and remain fully operational without internet or AI.

**Q: Can academic advisors override automatic equivalence recommendations?**  
*A:* Yes. The review screen provides dropdown overrides for every course. The engine recalculates credit reconciliations dynamically upon saving.
