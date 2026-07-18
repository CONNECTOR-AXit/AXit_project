package com.axit.ingestion.hwp;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

final class FixtureGenerator {
    private static final String HWP_MEDIA = "application/x-hwp";
    private static final String HWPX_MEDIA = "application/x-hwpx";

    private FixtureGenerator() {}

    static void generate(Path outputRoot, Path metadata) throws Exception {
        Path simpleHwp = outputRoot.resolve("hwp/simple.hwp");
        Path tableFootnoteHwp = outputRoot.resolve("hwp/table-footnote.hwp");
        Path simpleHwpx = outputRoot.resolve("hwpx/simple.hwpx");
        Path tableFootnoteHwpx = outputRoot.resolve("hwpx/table-footnote.hwpx");
        Path corruptHwp = outputRoot.resolve("malicious/corrupt.hwp");

        writeSimpleHwp(simpleHwp);
        writeTableFootnoteHwp(tableFootnoteHwp);
        writeSimpleHwpx(simpleHwpx);
        writeTableFootnoteHwpx(tableFootnoteHwpx);
        writeCorruptHwp(corruptHwp);
        writeMetadata(
                metadata,
                List.of(
                        fixture(
                                simpleHwp,
                                "hwp/simple.hwp",
                                HWP_MEDIA,
                                "OLE2 CFB / HWP 5",
                                List.of(HwpFixtureBuilder.SIMPLE_TEXT)),
                        fixture(
                                tableFootnoteHwp,
                                "hwp/table-footnote.hwp",
                                HWP_MEDIA,
                                "OLE2 CFB / HWP 5",
                                List.of(
                                        HwpFixtureBuilder.TABLE_BODY_TEXT,
                                        HwpFixtureBuilder.TABLE_TEXT[0][0],
                                        HwpFixtureBuilder.TABLE_TEXT[0][1],
                                        HwpFixtureBuilder.TABLE_TEXT[1][0],
                                        HwpFixtureBuilder.TABLE_TEXT[1][1],
                                        HwpFixtureBuilder.FOOTNOTE_TEXT)),
                        fixture(
                                simpleHwpx,
                                "hwpx/simple.hwpx",
                                HWPX_MEDIA,
                                "HWPX ZIP package (application/hwp+zip marker)",
                                List.of(HwpxFixtureBuilder.SIMPLE_TEXT)),
                        fixture(
                                tableFootnoteHwpx,
                                "hwpx/table-footnote.hwpx",
                                HWPX_MEDIA,
                                "HWPX ZIP package with table-cell and footnote controls",
                                List.of(
                                        HwpxFixtureBuilder.TABLE_BODY_TEXT,
                                        HwpxFixtureBuilder.TABLE_TEXT[0][0],
                                        HwpxFixtureBuilder.TABLE_TEXT[0][1],
                                        HwpxFixtureBuilder.TABLE_TEXT[1][0],
                                        HwpxFixtureBuilder.TABLE_TEXT[1][1],
                                        HwpxFixtureBuilder.FOOTNOTE_TEXT)),
                        errorFixture(
                                corruptHwp,
                                "malicious/corrupt.hwp",
                                HWP_MEDIA,
                                "truncated OLE2 CFB with genuine HWP magic",
                                "CORRUPT_DOCUMENT")));
    }

    static void writeSimpleHwp(Path output) throws Exception {
        HwpFixtureBuilder.writeSimple(output);
    }

    static void writeTableFootnoteHwp(Path output) throws Exception {
        HwpFixtureBuilder.writeTableAndFootnote(output);
    }

    static void writeSimpleHwpx(Path output) throws Exception {
        HwpxFixtureBuilder.writeSimple(output);
    }

    static void writeTableFootnoteHwpx(Path output) throws Exception {
        HwpxFixtureBuilder.writeTableAndFootnote(output);
    }

    static void writeCorruptHwp(Path output) throws Exception {
        Files.createDirectories(output.toAbsolutePath().normalize().getParent());
        Path valid = output.resolveSibling(output.getFileName() + ".valid.tmp");
        try {
            HwpFixtureBuilder.writeSimple(valid);
            byte[] bytes = Files.readAllBytes(valid);
            Files.write(output, java.util.Arrays.copyOf(bytes, 384));
        } finally {
            Files.deleteIfExists(valid);
        }
    }

    static void writeUnsafeHwpxForTest(Path output, String declaration) throws IOException {
        Map<String, byte[]> entries = new LinkedHashMap<>();
        entries.put("mimetype", "application/hwp+zip".getBytes(StandardCharsets.UTF_8));
        entries.put(
                "version.xml",
                ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                                + declaration
                                + "<version><x>unsafe-test-only</x></version>")
                        .getBytes(StandardCharsets.UTF_8));
        DeterministicZip.write(entries, output);
    }

    static void writeArchiveForTest(Path output, Map<String, byte[]> entries) throws IOException {
        DeterministicZip.write(entries, output);
    }

    private static FixtureDescription fixture(
            Path file,
            String relativePath,
            String mediaType,
            String classification,
            List<String> expectedText)
            throws IOException {
        return new FixtureDescription(
                relativePath,
                Files.size(file),
                Hashing.sha256(file),
                mediaType,
                "golden",
                classification,
                null,
                expectedText);
    }

    private static FixtureDescription errorFixture(
            Path file,
            String relativePath,
            String mediaType,
            String format,
            String expectedError)
            throws IOException {
        return new FixtureDescription(
                relativePath,
                Files.size(file),
                Hashing.sha256(file),
                mediaType,
                "malicious",
                format,
                expectedError,
                List.of());
    }

    private static void writeMetadata(Path output, List<FixtureDescription> fixtures)
            throws IOException {
        Files.createDirectories(output.toAbsolutePath().normalize().getParent());
        StringBuilder json = new StringBuilder(4096);
        json.append("{\n")
                .append("  \"fixture_license_spdx\": \"CC0-1.0\",\n")
                .append("  \"fixtures\": [\n");
        for (int index = 0; index < fixtures.size(); index++) {
            FixtureDescription fixture = fixtures.get(index);
            if (index > 0) {
                json.append(",\n");
            }
            json.append("    {\n")
                    .append("      \"anchor_kind\": \"hwp_paragraph\",\n")
                    .append("      \"bytes\": ")
                    .append(fixture.bytes())
                    .append(",\n")
                    .append("      \"classification\": ")
                    .append(JsonWriter.quote(fixture.classification()))
                    .append(",\n")
                    .append("      ");
            if (fixture.expectedError() != null) {
                json.append("\"expected_error\": ")
                        .append(JsonWriter.quote(fixture.expectedError()));
            } else {
                json.append("\"expected_nfc_text\": [");
                for (int textIndex = 0; textIndex < fixture.expectedText().size(); textIndex++) {
                    if (textIndex > 0) {
                        json.append(", ");
                    }
                    json.append(JsonWriter.quote(
                            TextNormalization.normalize(fixture.expectedText().get(textIndex))));
                }
                json.append(']');
            }
            json.append(",\n")
                    .append("      \"format\": ")
                    .append(JsonWriter.quote(fixture.format()))
                    .append(",\n")
                    .append("      \"media_type\": ")
                    .append(JsonWriter.quote(fixture.mediaType()))
                    .append(",\n")
                    .append("      \"path\": ")
                    .append(JsonWriter.quote(fixture.path()))
                    .append(",\n")
                    .append("      \"provenance\": \"Synthetic Korean text authored for AXit G0; no third-party document content\",\n")
                    .append("      \"sha256\": ")
                    .append(JsonWriter.quote(fixture.sha256()))
                    .append("\n")
                    .append("    }");
        }
        json.append("\n  ],\n")
                .append("  \"generator\": {\n")
                .append("    \"command\": \"spikes/document-ingestion/fixture_sources/hwp/generate.ps1\",\n")
                .append("    \"dependency_license_spdx\": \"Apache-2.0\",\n")
                .append("    \"hwplib\": \"1.1.10\",\n")
                .append("    \"hwpxlib\": \"1.0.9\",\n")
                .append("    \"java_feature\": \"17\"\n")
                .append("  },\n")
                .append("  \"schema_version\": \"axit.hwp-fixture-lane.v1\"\n")
                .append("}\n");
        Files.writeString(output, json, StandardCharsets.UTF_8);
    }

    private record FixtureDescription(
            String path,
            long bytes,
            String sha256,
            String mediaType,
            String classification,
            String format,
            String expectedError,
            List<String> expectedText) {}
}
