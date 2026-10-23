-- ============================================================================
-- Monitor de Análise (2026-07-08) — MySQL 8.4.
-- REUSA as colunas dormentes que o painel já tinha (status='aguardando_verificacao',
-- analysis_started_at, verified_at, rejected_at, check_count, whatsapp_asset_id).
-- Só adiciona as 5 colunas que faltavam de verdade (empresa/site + waba_status).
-- MySQL 8 NÃO aceita "ADD COLUMN IF NOT EXISTS" → o deploy real é feito pelo script
-- idempotente migrar_monitor_analise.py (checa SHOW COLUMNS e adiciona só o que falta).
-- Este arquivo fica como DOCUMENTAÇÃO do schema alvo.
-- ============================================================================

ALTER TABLE bm_records
  ADD COLUMN site_id      VARCHAR(64)  NULL,
  ADD COLUMN site_url     VARCHAR(255) NULL,
  ADD COLUMN cnpj         VARCHAR(32)  NULL,
  ADD COLUMN razao_social VARCHAR(255) NULL,
  ADD COLUMN waba_status  VARCHAR(24)  NULL,   -- aprovada|desabilitada|pendente|erro
  ALGORITHM=INSTANT;
