package com.axit.ingestion.hwp;

final class JsonWriter {
    private JsonWriter() {}

    static String envelope(ExtractionEnvelope envelope) {
        StringBuilder json = new StringBuilder(1024);
        json.append("{\"extraction_profile_hash\":")
                .append(quote(envelope.extractionProfileHash()))
                .append(",\"ok\":true,\"parser\":{\"name\":")
                .append(quote(envelope.parser().name()))
                .append(",\"version\":")
                .append(quote(envelope.parser().version()))
                .append("},\"records\":[");
        for (int index = 0; index < envelope.records().size(); index++) {
            if (index > 0) {
                json.append(',');
            }
            appendRecord(json, envelope.records().get(index));
        }
        json.append("],\"schema_version\":\"hwp-sidecar.v1\",\"source_sha256\":")
                .append(quote(envelope.sourceSha256()))
                .append(",\"warnings\":[");
        for (int index = 0; index < envelope.warnings().size(); index++) {
            if (index > 0) {
                json.append(',');
            }
            json.append(quote(envelope.warnings().get(index)));
        }
        return json.append("]}").toString();
    }

    private static void appendRecord(StringBuilder json, ExtractedRecord record) {
        json.append("{\"kind\":")
                .append(quote(record.kind().value()))
                .append(",\"locator\":{");
        Locator locator = record.locator();
        json.append("\"paragraph\":")
                .append(locator.paragraph())
                .append(",\"section\":")
                .append(locator.section());
        if (locator.table() != null) {
            json.append(",\"cell\":")
                    .append(locator.cell())
                    .append(",\"cell_paragraph\":")
                    .append(locator.cellParagraph())
                    .append(",\"table\":")
                    .append(locator.table())
                    .append(",\"table_block\":")
                    .append(locator.tableBlock())
                    .append(",\"table_row\":")
                    .append(locator.tableRow());
        } else if (locator.footnote() != null) {
            json.append(",\"footnote\":")
                    .append(locator.footnote())
                    .append(",\"footnote_paragraph\":")
                    .append(locator.footnoteParagraph());
        }
        json.append("},\"text\":")
                .append(quote(record.text()))
                .append(",\"text_fingerprint\":")
                .append(quote(Hashing.sha256(record.text())))
                .append('}');
    }

    static String quote(String value) {
        StringBuilder escaped = new StringBuilder(value.length() + 2).append('"');
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '"' -> escaped.append("\\\"");
                case '\\' -> escaped.append("\\\\");
                case '\b' -> escaped.append("\\b");
                case '\f' -> escaped.append("\\f");
                case '\n' -> escaped.append("\\n");
                case '\r' -> escaped.append("\\r");
                case '\t' -> escaped.append("\\t");
                default -> {
                    if (character < 0x20) {
                        escaped.append(String.format("\\u%04x", (int) character));
                    } else {
                        escaped.append(character);
                    }
                }
            }
        }
        return escaped.append('"').toString();
    }
}
