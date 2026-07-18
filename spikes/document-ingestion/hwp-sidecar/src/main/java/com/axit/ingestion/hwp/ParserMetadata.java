package com.axit.ingestion.hwp;

record ParserMetadata(String name, String version) {
    ParserMetadata {
        if (name == null || name.isBlank() || version == null || version.isBlank()) {
            throw new IllegalArgumentException("parser metadata is required");
        }
    }
}
