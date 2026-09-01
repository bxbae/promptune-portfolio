ALTER TABLE documents ADD company_id VARCHAR2(100) DEFAULT 'default-company';

UPDATE documents SET company_id = 'default-company' WHERE company_id IS NULL;
