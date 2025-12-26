import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Float, Text, ForeignKey, Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# -----------------------------
# DB setup
# -----------------------------
DB_URL = "sqlite:///bhph_crm.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

HOT_WARM_COLD = ["Hot", "Warm", "Cold"]
DEFAULT_TAGS = [
    "Need Driver's License",
    "Need Proof of Income",
    "Need Proof of Residence",
    "Need References",
    "Need Down Payment",
    "Need Insurance",
    "Need Stips",
    "Bankruptcy",
    "Repo",
    "First-Time Buyer",
    "Self-Employed",
]

class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # basic info
    first_name = Column(String, nullable=False, default="")
    last_name = Column(String, nullable=False, default="")
    phone = Column(String, nullable=True)
    phone2 = Column(String, nullable=True)
    email = Column(String, nullable=True)

    address1 = Column(String, nullable=True)
    address2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip = Column(String, nullable=True)

    source = Column(String, nullable=True)
    status = Column(String, default="Warm")  # Hot/Warm/Cold
    assigned_to = Column(String, nullable=True)

    tags = relationship("Tag", back_populates="lead", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="lead", cascade="all, delete-orphan")
    apps = relationship("FinanceApplication", back_populates="lead", cascade="all, delete-orphan")

    def full_name(self):
        return (f"{self.first_name} {self.last_name}").strip()

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    name = Column(String, nullable=False)

    lead = relationship("Lead", back_populates="tags")

class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    body = Column(Text, nullable=False)
    created_by = Column(String, nullable=True)

    lead = relationship("Lead", back_populates="notes")

class FinanceApplication(Base):
    __tablename__ = "finance_apps"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # income & employment
    gross_monthly_income = Column(Float, default=0.0)
    net_monthly_income = Column(Float, default=0.0)
    job_time_months = Column(Integer, default=0)
    employer = Column(String, nullable=True)
    pay_frequency = Column(String, nullable=True)  # weekly/biweekly/monthly

    # housing
    residence_time_months = Column(Integer, default=0)
    rent_or_mortgage = Column(Float, default=0.0)

    # debt & deal structure
    other_monthly_debt = Column(Float, default=0.0)
    desired_payment = Column(Float, default=0.0)
    down_payment = Column(Float, default=0.0)

    # credit indicators (simple flags)
    has_repo = Column(Boolean, default=False)
    has_bankruptcy = Column(Boolean, default=False)
    first_time_buyer = Column(Boolean, default=False)
    self_employed = Column(Boolean, default=False)

    # verification checklist
    dl_on_file = Column(Boolean, default=False)
    poi_on_file = Column(Boolean, default=False)  # proof of income
    por_on_file = Column(Boolean, default=False)  # proof of residence
    references_on_file = Column(Boolean, default=False)

    # scoring results
    score = Column(Integer, default=0)
    risk_tier = Column(String, default="Unknown")  # A/B/C/D
    decision = Column(String, default="Review")    # Approve/Counter/Review/Decline
    scoring_notes = Column(Text, default="")

    lead = relationship("Lead", back_populates="apps")

Base.metadata.create_all(engine)

# -----------------------------
# Underwriting / scoring logic
# -----------------------------
def compute_pti(net_income: float, desired_payment: float) -> float:
    if net_income <= 0:
        return 1.0
    return desired_payment / net_income

def score_application(app: FinanceApplication) -> tuple[int, str, str, str]:
    """
    Returns (score 0-100, risk_tier, decision, notes)
    Simple rule-based BHPH scoring; adjust weights to match your store.
    """
    notes = []
    score = 50  # baseline

    # Income strength
    if app.net_monthly_income >= 2500:
        score += 15
        notes.append("Net income strong (>= $2,500).")
    elif app.net_monthly_income >= 2000:
        score += 10
        notes.append("Net income good (>= $2,000).")
    elif app.net_monthly_income >= 1500:
        score += 5
        notes.append("Net income moderate (>= $1,500).")
    else:
        score -= 10
        notes.append("Net income low (< $1,500).")

    # PTI (payment-to-income)
    pti = compute_pti(app.net_monthly_income, app.desired_payment)
    if pti <= 0.20:
        score += 15
        notes.append(f"PTI excellent ({pti:.0%}).")
    elif pti <= 0.25:
        score += 10
        notes.append(f"PTI good ({pti:.0%}).")
    elif pti <= 0.30:
        score += 0
        notes.append(f"PTI borderline ({pti:.0%}).")
    else:
        score -= 15
        notes.append(f"PTI high ({pti:.0%}).")

    # Job time
    if app.job_time_months >= 24:
        score += 10
        notes.append("Job time strong (>= 24 mo).")
    elif app.job_time_months >= 12:
        score += 5
        notes.append("Job time ok (>= 12 mo).")
    else:
        score -= 10
        notes.append("Job time short (< 12 mo).")

    # Residence time
    if app.residence_time_months >= 24:
        score += 8
        notes.append("Residence time strong (>= 24 mo).")
    elif app.residence_time_months >= 12:
        score += 4
        notes.append("Residence time ok (>= 12 mo).")
    else:
        score -= 6
        notes.append("Residence time short (< 12 mo).")

    # Down payment
    if app.down_payment >= 1500:
        score += 10
        notes.append("Down payment strong (>= $1,500).")
    elif app.down_payment >= 999:
        score += 6
        notes.append("Down payment ok (>= $999).")
    elif app.down_payment > 0:
        score += 2
        notes.append("Down payment low (< $999).")
    else:
        score -= 8
        notes.append("No down payment.")

    # Red flags
    if app.has_repo:
        score -= 6
        notes.append("Repo history flagged.")
    if app.has_bankruptcy:
        score -= 6
        notes.append("Bankruptcy history flagged.")
    if app.self_employed:
        score -= 2
        notes.append("Self-employed: verify income carefully.")
    if app.first_time_buyer:
        score -= 1
        notes.append("First-time buyer.")

    # Missing stips penalty
    missing = []
    if not app.dl_on_file: missing.append("DL")
    if not app.poi_on_file: missing.append("POI")
    if not app.por_on_file: missing.append("POR")
    if not app.references_on_file: missing.append("Refs")
    if missing:
        score -= min(12, 3 * len(missing))
        notes.append(f"Missing stips: {', '.join(missing)}.")

    # Clamp score
    score = max(0, min(100, score))

    # Tier + decision
    if score >= 80:
        tier = "A"
        decision = "Approve"
    elif score >= 65:
        tier = "B"
        decision = "Approve"
    elif score >= 50:
        tier = "C"
        decision = "Review"
    else:
        tier = "D"
        decision = "Counter" if app.down_payment < 999 else "Decline"

    return score, tier, decision, " ".join(notes)

# -----------------------------
# Helpers
# -----------------------------
def get_db():
    return SessionLocal()

def lead_to_row(lead: Lead):
    return {
        "ID": lead.id,
        "Created": lead.created_at.strftime("%Y-%m-%d %H:%M"),
        "Name": lead.full_name(),
        "Phone": lead.phone,
        "Email": lead.email,
        "City": lead.city,
        "State": lead.state,
        "Status": lead.status,
        "Source": lead.source,
        "Assigned To": lead.assigned_to,
        "Tags": ", ".join(sorted({t.name for t in lead.tags})),
        "Apps": len(lead.apps),
        "Last Note": (max(lead.notes, key=lambda n: n.created_at).created_at.strftime("%Y-%m-%d %H:%M")
                      if lead.notes else ""),
    }

def safe_str(x):
    if pd.isna(x):
        return ""
    return str(x).strip()

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="BHPH CRM", layout="wide")
st.title("BHPH CRM (Leads • Finance Apps • Notes • Tags • Underwriting Score)")

db = get_db()

with st.sidebar:
    st.header("Navigation")
    page = st.radio("Go to", ["Dashboard", "Import Leads", "Create Lead", "Lead Detail", "Underwriting Queue"])
    st.divider()
    st.caption("Database: bhph_crm.db (SQLite)")
    st.caption("Tip: keep PII secured; add logins before production use.")

# -----------------------------
# Dashboard
# -----------------------------
if page == "Dashboard":
    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Leads", len(leads))
    col2.metric("Hot", sum(1 for l in leads if l.status == "Hot"))
    col3.metric("Warm", sum(1 for l in leads if l.status == "Warm"))
    col4.metric("Cold", sum(1 for l in leads if l.status == "Cold"))

    df = pd.DataFrame([lead_to_row(l) for l in leads])
    st.dataframe(df, use_container_width=True, hide_index=True)

# -----------------------------
# Import Leads
# -----------------------------
elif page == "Import Leads":
    st.subheader("Import Incoming Leads (CSV or XLSX)")
    st.write("Upload a file with columns like: first_name, last_name, phone, email, address1, city, state, zip, source, status, assigned_to")

    uploaded = st.file_uploader("Upload CSV or XLSX", type=["csv", "xlsx"])
    if uploaded:
        try:
            if uploaded.name.lower().endswith(".csv"):
                df = pd.read_csv(uploaded)
            else:
                df = pd.read_excel(uploaded)

            st.write("Preview:")
            st.dataframe(df.head(50), use_container_width=True)

            if st.button("Import These Leads"):
                imported = 0
                for _, row in df.iterrows():
                    lead = Lead(
                        first_name=safe_str(row.get("first_name", "")),
                        last_name=safe_str(row.get("last_name", "")),
                        phone=safe_str(row.get("phone", "")),
                        phone2=safe_str(row.get("phone2", "")),
                        email=safe_str(row.get("email", "")),
                        address1=safe_str(row.get("address1", "")),
                        address2=safe_str(row.get("address2", "")),
                        city=safe_str(row.get("city", "")),
                        state=safe_str(row.get("state", "")),
                        zip=safe_str(row.get("zip", "")),
                        source=safe_str(row.get("source", "")),
                        status=safe_str(row.get("status", "Warm")) or "Warm",
                        assigned_to=safe_str(row.get("assigned_to", "")),
                    )
                    if lead.status not in HOT_WARM_COLD:
                        lead.status = "Warm"
                    db.add(lead)
                    imported += 1
                db.commit()
                st.success(f"Imported {imported} leads.")
        except Exception as e:
            st.error(f"Import failed: {e}")

    st.divider()
    st.subheader("Sample CSV Header")
    st.code(
        "first_name,last_name,phone,phone2,email,address1,address2,city,state,zip,source,status,assigned_to",
        language="text"
    )

# -----------------------------
# Create Lead
# -----------------------------
elif page == "Create Lead":
    st.subheader("Create a Lead")
    with st.form("create_lead"):
        c1, c2, c3 = st.columns(3)
        first_name = c1.text_input("First Name")
        last_name = c2.text_input("Last Name")
        status = c3.selectbox("Status", HOT_WARM_COLD, index=1)

        c4, c5, c6 = st.columns(3)
        phone = c4.text_input("Phone")
        phone2 = c5.text_input("Phone 2")
        email = c6.text_input("Email")

        c7, c8, c9 = st.columns(3)
        address1 = c7.text_input("Address 1")
        city = c8.text_input("City")
        state = c9.text_input("State")

        c10, c11, c12 = st.columns(3)
        zipc = c10.text_input("ZIP")
        source = c11.text_input("Source (FB, Website, Walk-in, etc.)")
        assigned_to = c12.text_input("Assigned To")

        submitted = st.form_submit_button("Save Lead")
        if submitted:
            if not first_name and not last_name:
                st.error("Add at least a first or last name.")
            else:
                lead = Lead(
                    first_name=first_name.strip(),
                    last_name=last_name.strip(),
                    status=status,
                    phone=phone.strip(),
                    phone2=phone2.strip(),
                    email=email.strip(),
                    address1=address1.strip(),
                    city=city.strip(),
                    state=state.strip(),
                    zip=zipc.strip(),
                    source=source.strip(),
                    assigned_to=assigned_to.strip(),
                )
                db.add(lead)
                db.commit()
                st.success(f"Created lead #{lead.id}: {lead.full_name()}")

# -----------------------------
# Lead Detail
# -----------------------------
elif page == "Lead Detail":
    st.subheader("Lead Detail")
    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    if not leads:
        st.info("No leads yet. Import or create one first.")
    else:
        lead_options = {f"#{l.id} • {l.full_name()} • {l.phone or ''} • {l.status}": l.id for l in leads}
        selected = st.selectbox("Select Lead", list(lead_options.keys()))
        lead_id = lead_options[selected]
        lead = db.query(Lead).filter(Lead.id == lead_id).first()

        left, right = st.columns([1.2, 1])

        with left:
            st.markdown("### Customer Info")
            with st.form("update_lead"):
                c1, c2, c3 = st.columns(3)
                lead.first_name = c1.text_input("First Name", value=lead.first_name or "")
                lead.last_name = c2.text_input("Last Name", value=lead.last_name or "")
                lead.status = c3.selectbox("Status", HOT_WARM_COLD, index=HOT_WARM_COLD.index(lead.status or "Warm"))

                c4, c5, c6 = st.columns(3)
                lead.phone = c4.text_input("Phone", value=lead.phone or "")
                lead.phone2 = c5.text_input("Phone 2", value=lead.phone2 or "")
                lead.email = c6.text_input("Email", value=lead.email or "")

                c7, c8, c9 = st.columns(3)
                lead.address1 = c7.text_input("Address 1", value=lead.address1 or "")
                lead.city = c8.text_input("City", value=lead.city or "")
                lead.state = c9.text_input("State", value=lead.state or "")

                c10, c11, c12 = st.columns(3)
                lead.zip = c10.text_input("ZIP", value=lead.zip or "")
                lead.source = c11.text_input("Source", value=lead.source or "")
                lead.assigned_to = c12.text_input("Assigned To", value=lead.assigned_to or "")

                if st.form_submit_button("Save Changes"):
                    db.commit()
                    st.success("Lead updated.")

            st.markdown("### Tags / Stips Needed")
            existing_tags = sorted({t.name for t in lead.tags})
            new_tags = st.multiselect("Select tags", options=sorted(set(DEFAULT_TAGS + existing_tags)), default=existing_tags)

            if st.button("Update Tags"):
                # Replace tags
                lead.tags.clear()
                for t in new_tags:
                    lead.tags.append(Tag(name=t))
                db.commit()
                st.success("Tags updated.")

            st.markdown("### Notes")
            with st.form("add_note"):
                note_body = st.text_area("Add a note", height=120)
                created_by = st.text_input("Created by (optional)", value="")
                if st.form_submit_button("Save Note"):
                    if not note_body.strip():
                        st.error("Note can't be empty.")
                    else:
                        db.add(Note(lead_id=lead.id, body=note_body.strip(), created_by=created_by.strip() or None))
                        db.commit()
                        st.success("Note saved.")

            notes = db.query(Note).filter(Note.lead_id == lead.id).order_by(Note.created_at.desc()).all()
            for n in notes[:20]:
                st.markdown(
                    f"**{n.created_at.strftime('%Y-%m-%d %H:%M')}**"
                    + (f" • _{n.created_by}_" if n.created_by else "")
                )
                st.write(n.body)
                st.divider()

        with right:
            st.markdown("### Finance Applications")
            st.caption("Create a finance app, run underwriting score, and store the result.")
            with st.form("create_app"):
                c1, c2 = st.columns(2)
                net = c1.number_input("Net Monthly Income", min_value=0.0, step=50.0, value=2000.0)
                gross = c2.number_input("Gross Monthly Income", min_value=0.0, step=50.0, value=2500.0)

                c3, c4 = st.columns(2)
                job_mo = c3.number_input("Job Time (months)", min_value=0, step=1, value=12)
                res_mo = c4.number_input("Residence Time (months)", min_value=0, step=1, value=12)

                c5, c6 = st.columns(2)
                rent = c5.number_input("Rent/Mortgage (monthly)", min_value=0.0, step=25.0, value=800.0)
                debt = c6.number_input("Other Monthly Debt", min_value=0.0, step=25.0, value=150.0)

                c7, c8 = st.columns(2)
                desired_payment = c7.number_input("Desired Payment", min_value=0.0, step=10.0, value=450.0)
                down = c8.number_input("Down Payment", min_value=0.0, step=50.0, value=999.0)

                c9, c10 = st.columns(2)
                employer = c9.text_input("Employer (optional)", value="")
                pay_freq = c10.selectbox("Pay Frequency", ["weekly", "biweekly", "monthly"], index=1)

                st.markdown("**Credit / Profile Flags**")
                f1, f2 = st.columns(2)
                has_repo = f1.checkbox("Repo", value=False)
                has_bk = f2.checkbox("Bankruptcy", value=False)

                f3, f4 = st.columns(2)
                first_time = f3.checkbox("First-Time Buyer", value=False)
                self_emp = f4.checkbox("Self-Employed", value=False)

                st.markdown("**Stips On File**")
                s1, s2 = st.columns(2)
                dl = s1.checkbox("Driver's License", value=False)
                poi = s2.checkbox("Proof of Income", value=False)

                s3, s4 = st.columns(2)
                por = s3.checkbox("Proof of Residence", value=False)
                refs = s4.checkbox("References", value=False)

                run_score = st.checkbox("Run underwriting score now", value=True)

                if st.form_submit_button("Save Finance Application"):
                    app = FinanceApplication(
                        lead_id=lead.id,
                        gross_monthly_income=float(gross),
                        net_monthly_income=float(net),
                        job_time_months=int(job_mo),
                        residence_time_months=int(res_mo),
                        rent_or_mortgage=float(rent),
                        other_monthly_debt=float(debt),
                        desired_payment=float(desired_payment),
                        down_payment=float(down),
                        employer=employer.strip() or None,
                        pay_frequency=pay_freq,
                        has_repo=bool(has_repo),
                        has_bankruptcy=bool(has_bk),
                        first_time_buyer=bool(first_time),
                        self_employed=bool(self_emp),
                        dl_on_file=bool(dl),
                        poi_on_file=bool(poi),
                        por_on_file=bool(por),
                        references_on_file=bool(refs),
                    )
                    if run_score:
                        sc, tier, decision, sc_notes = score_application(app)
                        app.score = sc
                        app.risk_tier = tier
                        app.decision = decision
                        app.scoring_notes = sc_notes

                    db.add(app)
                    db.commit()
                    st.success(f"Saved finance application #{app.id} (Score: {app.score}, Tier: {app.risk_tier}, Decision: {app.decision})")

            apps = db.query(FinanceApplication).filter(FinanceApplication.lead_id == lead.id).order_by(FinanceApplication.created_at.desc()).all()
            if not apps:
                st.info("No finance apps yet.")
            else:
                for a in apps[:10]:
                    pti = compute_pti(a.net_monthly_income, a.desired_payment)
                    st.markdown(f"**App #{a.id}** • {a.created_at.strftime('%Y-%m-%d %H:%M')}")
                    st.write(
                        f"Net Income: ${a.net_monthly_income:,.0f} | Payment: ${a.desired_payment:,.0f} | PTI: {pti:.0%} | "
                        f"Down: ${a.down_payment:,.0f}"
                    )
                    st.write(f"Score: **{a.score}** | Tier: **{a.risk_tier}** | Decision: **{a.decision}**")
                    if a.scoring_notes:
                        st.caption(a.scoring_notes)
                    st.divider()

# -----------------------------
# Underwriting Queue
# -----------------------------
elif page == "Underwriting Queue":
    st.subheader("Underwriting Queue")
    st.write("Shows the most recent finance app per lead, sorted by score (low to high) for quick review.")

    leads = db.query(Lead).all()
    rows = []
    for l in leads:
        apps = sorted(l.apps, key=lambda a: a.created_at, reverse=True)
        if not apps:
            continue
        a = apps[0]
        pti = compute_pti(a.net_monthly_income, a.desired_payment)
        rows.append({
            "Lead ID": l.id,
            "Name": l.full_name(),
            "Status": l.status,
            "Phone": l.phone,
            "Tags": ", ".join(sorted({t.name for t in l.tags})),
            "App ID": a.id,
            "Score": a.score,
            "Tier": a.risk_tier,
            "Decision": a.decision,
            "PTI": f"{pti:.0%}",
            "Down": f"${a.down_payment:,.0f}",
            "Net Income": f"${a.net_monthly_income:,.0f}",
            "Created": a.created_at.strftime("%Y-%m-%d %H:%M"),
        })

    if not rows:
        st.info("No finance apps found yet.")
    else:
        df = pd.DataFrame(rows).sort_values(by=["Score", "Tier"], ascending=[True, True])
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.caption("Next steps for production: user login, permissions by store, document uploads, audit logs, encryption-at-rest.")
