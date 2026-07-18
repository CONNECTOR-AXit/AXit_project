package com.axit.ingestion.hwp;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

final class RecordCollector {
    private static final int MAX_RECORDS = 10_000;
    private static final int MAX_RECORD_CODE_POINTS = 100_000;
    private static final int MAX_TOTAL_CODE_POINTS = 1_000_000;

    private final List<ExtractedRecord> records = new ArrayList<>();
    private final Set<String> warnings = new LinkedHashSet<>();
    private int totalCodePoints;

    void add(RecordKind kind, String rawText, Locator locator) throws ExtractionFailure {
        String text = TextNormalization.normalize(rawText);
        if (text.isBlank()) {
            return;
        }
        if (!TextNormalization.hasValidSurrogates(text)) {
            throw ExtractionFailure.of(
                    "CORRUPT_DOCUMENT",
                    "The document contains malformed Unicode text.");
        }
        int codePoints = text.codePointCount(0, text.length());
        if (codePoints > MAX_RECORD_CODE_POINTS) {
            throw ExtractionFailure.of(
                    "OUTPUT_LIMIT_EXCEEDED",
                    "A document text record exceeds the approved output bound.");
        }
        if (records.size() >= MAX_RECORDS || totalCodePoints + codePoints > MAX_TOTAL_CODE_POINTS) {
            throw ExtractionFailure.of(
                    "OUTPUT_LIMIT_EXCEEDED",
                    "The extracted document exceeds the approved output bound.");
        }
        records.add(new ExtractedRecord(kind, text, locator));
        totalCodePoints += codePoints;
    }

    void warn(String warning) {
        if (warning != null && warning.matches("[A-Z][A-Z0-9_]*")) {
            warnings.add(warning);
        }
    }

    List<ExtractedRecord> records() {
        return List.copyOf(records);
    }

    List<String> warnings() {
        return List.copyOf(warnings);
    }
}
