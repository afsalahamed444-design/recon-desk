from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
                        MetaData, String, Table, Text, create_engine, func)

from .config import settings

if settings.database_url.startswith("sqlite"):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)

md = MetaData()
now = func.now()

users = Table("users", md,
    Column("id", Integer, primary_key=True), Column("email", String(200), unique=True, nullable=False),
    Column("name", String(100)), Column("password_hash", String(300), nullable=False),
    Column("role", String(30), nullable=False))  # finance_exec | cofounder

partners = Table("partners", md,
    Column("id", Integer, primary_key=True), Column("name", String(100), unique=True, nullable=False),
    Column("type", String(20), nullable=False))  # channel | courier

rate_cards = Table("rate_cards", md,
    Column("id", Integer, primary_key=True), Column("partner_id", ForeignKey("partners.id"), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("commission_pct", Float, default=0), Column("prepaid_fee_pct", Float, default=0),
    Column("cod_fee_pct", Float, default=0), Column("fixed_fee", Float, default=0),
    Column("return_fee_pct", Float, default=0), Column("remit_days", Integer, default=7),
    Column("cod_by_courier", Boolean, default=False),
    Column("weight_slabs", JSON))  # couriers: [{"upto_kg":0.5,"rate":45}, ...]

mapping_versions = Table("mapping_versions", md,
    Column("id", Integer, primary_key=True), Column("source", String(20), nullable=False),
    Column("version", Integer, nullable=False), Column("mapping", JSON, nullable=False),
    Column("created_by", String(200)), Column("created_at", DateTime, server_default=now),
    Column("active", Boolean, default=False), Column("origin", String(20)))  # ai | fuzzy | saved | manual

uploads = Table("uploads", md,
    Column("id", Integer, primary_key=True), Column("source", String(20), nullable=False),
    Column("filename", String(300)), Column("file_hash", String(64), unique=True),
    Column("status", String(20), default="uploaded"),  # uploaded | processing | done | failed
    Column("rows_total", Integer, default=0), Column("rows_loaded", Integer, default=0),
    Column("rows_rejected", Integer, default=0), Column("rows_duplicate", Integer, default=0),
    Column("headers", JSON), Column("notes", JSON), Column("error", Text),
    Column("mapping_version_id", Integer), Column("seconds", Float),
    Column("created_by", String(200)), Column("created_at", DateTime, server_default=now))

orders = Table("orders", md,
    Column("order_id", String(60), primary_key=True), Column("channel", String(60), index=True),
    Column("courier", String(60)), Column("order_date", Date), Column("value", Float),
    Column("payment_mode", String(10)), Column("delivery_status", String(60)),
    Column("delivery_date", Date), Column("weight_kg", Float), Column("warehouse_received_date", Date),
    Column("customer_name", String(200)), Column("phone", String(30)))  # PII: masked in API

settlement_lines = Table("settlement_lines", md,
    Column("id", Integer, primary_key=True), Column("order_id", String(60), index=True),
    Column("settled_amount", Float), Column("tcs", Float, default=0), Column("tds", Float, default=0),
    Column("settlement_date", Date), Column("upload_id", Integer))

cod_remittances = Table("cod_remittances", md,
    Column("id", Integer, primary_key=True), Column("order_id", String(60), index=True),
    Column("remitted_amount", Float), Column("remittance_date", Date), Column("upload_id", Integer))

freight_invoices = Table("freight_invoices", md,
    Column("id", Integer, primary_key=True), Column("order_id", String(60), index=True),
    Column("billed_amount", Float), Column("billed_weight_kg", Float), Column("upload_id", Integer))

order_recon = Table("order_recon", md,
    Column("order_id", String(60), primary_key=True), Column("channel", String(60), index=True),
    Column("courier", String(60)), Column("payment_mode", String(10)), Column("delivery_status", String(60)),
    Column("order_date", Date), Column("delivery_date", Date), Column("value", Float),
    Column("status", String(30), index=True), Column("flags", String(200)),
    Column("commission", Float), Column("prepaid_fee", Float), Column("cod_fee", Float),
    Column("fixed_fee", Float), Column("return_fee", Float),
    Column("expected", Float), Column("received", Float), Column("diff", Float),
    Column("tcs", Float), Column("tds", Float),
    Column("weight_kg", Float), Column("billed_weight_kg", Float),
    Column("expected_freight", Float), Column("billed_freight", Float),
    Column("due_date", Date), Column("age_days", Integer), Column("pay_lines", Integer))

claims = Table("claims", md,
    Column("id", Integer, primary_key=True), Column("order_id", String(60), index=True),
    Column("partner", String(100), index=True), Column("type", String(30), index=True),
    Column("amount", Float), Column("age_days", Integer), Column("status", String(20), default="open"),
    Column("evidence", JSON), Column("created_at", DateTime, server_default=now),
    Index("ix_claim_key", "order_id", "type", unique=True))

recon_runs = Table("recon_runs", md,
    Column("id", Integer, primary_key=True), Column("as_of", Date), Column("seconds", Float),
    Column("orders", Integer), Column("counts", JSON), Column("created_by", String(200)),
    Column("created_at", DateTime, server_default=now))

audit_log = Table("audit_log", md,
    Column("id", Integer, primary_key=True), Column("user_email", String(200)),
    Column("action", String(60)), Column("detail", Text), Column("at", DateTime, server_default=now))


def init_db():
    md.create_all(engine)
