package com.axit.ingestion.hwp;

enum RecordKind {
    PARAGRAPH("paragraph"),
    TABLE_CELL("table_cell"),
    FOOTNOTE("footnote");

    private final String value;

    RecordKind(String value) {
        this.value = value;
    }

    String value() {
        return value;
    }
}
