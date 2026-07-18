package com.axit.ingestion.hwp;

record ExtractedRecord(RecordKind kind, String text, Locator locator) {
    ExtractedRecord {
        if (kind == null || locator == null || text == null || text.isBlank()) {
            throw new IllegalArgumentException("record kind, locator, and non-empty text are required");
        }
    }
}
