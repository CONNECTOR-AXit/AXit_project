package com.axit.ingestion.hwp;

import java.util.List;

record ExtractionEnvelope(
        String sourceSha256,
        String extractionProfileHash,
        ParserMetadata parser,
        List<ExtractedRecord> records,
        List<String> warnings) {

    ExtractionEnvelope {
        if (!Hashing.isSha256(sourceSha256) || !Hashing.isSha256(extractionProfileHash)) {
            throw new IllegalArgumentException("source and profile identities must be lowercase SHA-256 values");
        }
        if (parser == null || records == null || warnings == null) {
            throw new IllegalArgumentException("envelope fields are required");
        }
        records = List.copyOf(records);
        warnings = List.copyOf(warnings);
    }

    String toJson() {
        return JsonWriter.envelope(this);
    }
}
