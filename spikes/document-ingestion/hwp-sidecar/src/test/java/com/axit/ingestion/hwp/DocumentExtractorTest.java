package com.axit.ingestion.hwp;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipFile;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

final class DocumentExtractorTest {
    private static final String PROFILE_HASH = "a".repeat(64);
    private static final byte[] CFB_MAGIC = HexFormat.of().parseHex("d0cf11e0a1b11ae1");

    @TempDir
    Path tempDir;

    @Test
    void generatedHwpIsGenuineAndParagraphLocatorIsStable() throws Exception {
        Path fixture = tempDir.resolve("simple.hwp");
        FixtureGenerator.writeSimpleHwp(fixture);

        assertArrayEquals(CFB_MAGIC, Arrays.copyOf(Files.readAllBytes(fixture), CFB_MAGIC.length));
        ExtractionEnvelope first = DocumentExtractor.extract(fixture, MediaType.HWP, PROFILE_HASH);
        ExtractionEnvelope second = DocumentExtractor.extract(fixture, MediaType.HWP, PROFILE_HASH);

        assertEquals("hwplib", first.parser().name());
        assertEquals("1.1.10", first.parser().version());
        assertEquals(first.toJson(), second.toJson());
        ExtractedRecord paragraph = first.records().stream()
                .filter(record -> record.kind() == RecordKind.PARAGRAPH)
                .findFirst()
                .orElseThrow();
        assertEquals(0, paragraph.locator().section());
        assertEquals(0, paragraph.locator().paragraph());
        assertTrue(paragraph.text().contains("회의 사전 브리핑"));
    }

    @Test
    void hwpTableAndFootnoteRoundTripWithCompletePaths() throws Exception {
        Path fixture = tempDir.resolve("table-footnote.hwp");
        FixtureGenerator.writeTableFootnoteHwp(fixture);

        ExtractionEnvelope result = DocumentExtractor.extract(fixture, MediaType.HWP, PROFILE_HASH);
        assertTrue(result.records().stream().anyMatch(record ->
                record.kind() == RecordKind.TABLE_CELL
                        && Integer.valueOf(0).equals(record.locator().table())
                        && Integer.valueOf(0).equals(record.locator().tableBlock())
                        && Integer.valueOf(1).equals(record.locator().tableRow())
                        && Integer.valueOf(1).equals(record.locator().cell())
                        && Integer.valueOf(0).equals(record.locator().cellParagraph())
                        && record.text().contains("후속 담당")));
        assertTrue(result.records().stream().anyMatch(record ->
                record.kind() == RecordKind.FOOTNOTE
                        && Integer.valueOf(0).equals(record.locator().footnote())
                        && Integer.valueOf(0).equals(record.locator().footnoteParagraph())
                        && record.text().contains("검토 기준일")));
        assertFalse(result.warnings().contains("UNSUPPORTED_FOOTNOTE"));
    }

    @Test
    void generatedHwpxIsValidPackageAndExtractsParagraph() throws Exception {
        Path fixture = tempDir.resolve("simple.hwpx");
        FixtureGenerator.writeSimpleHwpx(fixture);

        byte[] bytes = Files.readAllBytes(fixture);
        assertEquals('P', bytes[0]);
        assertEquals('K', bytes[1]);
        ExtractionEnvelope result = DocumentExtractor.extract(fixture, MediaType.HWPX, PROFILE_HASH);

        assertEquals("hwpxlib", result.parser().name());
        assertEquals("1.0.9", result.parser().version());
        assertTrue(result.records().stream().anyMatch(record ->
                record.kind() == RecordKind.PARAGRAPH
                        && record.locator().section() == 0
                        && record.locator().paragraph() == 0
                        && record.text().contains("안건과 근거")));
        try (ZipFile zip = new ZipFile(fixture.toFile())) {
            assertEquals("application/hwp+zip", new String(
                    zip.getInputStream(zip.getEntry("mimetype")).readAllBytes(),
                    StandardCharsets.UTF_8));
            assertTrue(zip.getEntry("META-INF/container.xml") != null);
            assertTrue(zip.getEntry("Contents/content.hpf") != null);
            assertTrue(zip.getEntry("Contents/section0.xml") != null);
        }
    }

    @Test
    void hwpxTableAndFootnoteRoundTripWithCompletePaths() throws Exception {
        Path fixture = tempDir.resolve("table-footnote.hwpx");
        FixtureGenerator.writeTableFootnoteHwpx(fixture);

        ExtractionEnvelope first = DocumentExtractor.extract(fixture, MediaType.HWPX, PROFILE_HASH);
        ExtractionEnvelope second = DocumentExtractor.extract(fixture, MediaType.HWPX, PROFILE_HASH);

        assertEquals(first.toJson(), second.toJson());
        assertTrue(first.records().stream().anyMatch(record ->
                record.kind() == RecordKind.TABLE_CELL
                        && Integer.valueOf(0).equals(record.locator().table())
                        && Integer.valueOf(0).equals(record.locator().tableBlock())
                        && Integer.valueOf(1).equals(record.locator().tableRow())
                        && Integer.valueOf(1).equals(record.locator().cell())
                        && Integer.valueOf(0).equals(record.locator().cellParagraph())
                        && record.text().contains("HWPX 후속 담당")));
        assertTrue(first.records().stream().anyMatch(record ->
                record.kind() == RecordKind.FOOTNOTE
                        && Integer.valueOf(0).equals(record.locator().footnote())
                        && Integer.valueOf(0).equals(record.locator().footnoteParagraph())
                        && record.text().contains("HWPX 검토 기준일")));
        assertFalse(first.warnings().contains("UNSUPPORTED_ENDNOTE"));
    }

    @Test
    void corruptInputUsesTypedFailureWithoutRawParserText() throws Exception {
        Path fixture = tempDir.resolve("broken.hwp");
        Files.writeString(fixture, "not a compound file");

        ExtractionFailure failure = assertThrows(
                ExtractionFailure.class,
                () -> DocumentExtractor.extract(fixture, MediaType.HWP, PROFILE_HASH));
        assertEquals("TYPE_MISMATCH", failure.code());
        assertEquals("The input does not match the declared document type.", failure.publicMessage());
        assertFalse(failure.toJson().contains("compound"));
    }

    @Test
    void structurallyCorruptHwpKeepsMagicButUsesCorruptDocumentFailure() throws Exception {
        Path fixture = tempDir.resolve("corrupt.hwp");
        FixtureGenerator.writeCorruptHwp(fixture);

        assertArrayEquals(CFB_MAGIC, Arrays.copyOf(Files.readAllBytes(fixture), CFB_MAGIC.length));
        ExtractionFailure failure = assertThrows(
                ExtractionFailure.class,
                () -> DocumentExtractor.extract(fixture, MediaType.HWP, PROFILE_HASH));
        assertEquals("CORRUPT_DOCUMENT", failure.code());
        assertFalse(failure.toJson().contains(fixture.toString()));
    }

    @Test
    void hwpxDtdIsRejectedBeforeThirdPartyParser() throws Exception {
        Path fixture = tempDir.resolve("xxe.hwpx");
        FixtureGenerator.writeUnsafeHwpxForTest(fixture, "<!DOCTYPE x [<!ENTITY leak SYSTEM 'file:///etc/passwd'>]>");

        ExtractionFailure failure = assertThrows(
                ExtractionFailure.class,
                () -> DocumentExtractor.extract(fixture, MediaType.HWPX, PROFILE_HASH));
        assertEquals("XML_DTD_FORBIDDEN", failure.code());
        assertFalse(failure.toJson().contains("/etc/passwd"));
    }

    @Test
    void hwpxMediaMarkerMustMatchExactly() throws Exception {
        Path fixture = tempDir.resolve("wrong-media.hwpx");
        Map<String, byte[]> entries = new LinkedHashMap<>();
        entries.put("mimetype", "application/zip".getBytes(StandardCharsets.UTF_8));
        entries.put("version.xml", "<version/>".getBytes(StandardCharsets.UTF_8));
        FixtureGenerator.writeArchiveForTest(fixture, entries);

        ExtractionFailure failure = assertThrows(
                ExtractionFailure.class, () -> HwpxPreflight.verify(fixture));
        assertEquals("TYPE_MISMATCH", failure.code());
    }

    @Test
    void hwpxTraversalAndCompressionBombAreRejectedByPreflight() throws Exception {
        Path traversal = tempDir.resolve("traversal.hwpx");
        Map<String, byte[]> traversalEntries = new LinkedHashMap<>();
        traversalEntries.put("mimetype", "application/hwp+zip".getBytes(StandardCharsets.UTF_8));
        traversalEntries.put("../secret.xml", "<x/>".getBytes(StandardCharsets.UTF_8));
        FixtureGenerator.writeArchiveForTest(traversal, traversalEntries);
        assertEquals(
                "ARCHIVE_PATH_REJECTED",
                assertThrows(ExtractionFailure.class, () -> HwpxPreflight.verify(traversal)).code());

        Path bomb = tempDir.resolve("bomb.hwpx");
        Map<String, byte[]> bombEntries = new LinkedHashMap<>();
        bombEntries.put("mimetype", "application/hwp+zip".getBytes(StandardCharsets.UTF_8));
        bombEntries.put("Contents/bomb.xml", new byte[900 * 1024]);
        FixtureGenerator.writeArchiveForTest(bomb, bombEntries);
        assertEquals(
                "ARCHIVE_RATIO_REJECTED",
                assertThrows(ExtractionFailure.class, () -> HwpxPreflight.verify(bomb)).code());
        assertFalse(HwpxPreflight.exceedsCompressionRatio(10_000, 100));
        assertTrue(HwpxPreflight.exceedsCompressionRatio(10_001, 100));
        assertTrue(HwpxPreflight.exceedsCompressionRatio(1, 0));
    }

    @Test
    void fixtureGenerationIsByteDeterministicAndMetadataTracksHashes() throws Exception {
        Path firstRoot = tempDir.resolve("first");
        Path secondRoot = tempDir.resolve("second");
        Path firstMetadata = tempDir.resolve("first-metadata.json");
        Path secondMetadata = tempDir.resolve("second-metadata.json");
        FixtureGenerator.generate(firstRoot, firstMetadata);
        FixtureGenerator.generate(secondRoot, secondMetadata);

        for (String path : new String[] {
            "hwp/simple.hwp",
            "hwp/table-footnote.hwp",
            "hwpx/simple.hwpx",
            "hwpx/table-footnote.hwpx",
            "malicious/corrupt.hwp"
        }) {
            assertArrayEquals(
                    Files.readAllBytes(firstRoot.resolve(path)),
                    Files.readAllBytes(secondRoot.resolve(path)),
                    path);
        }
        assertArrayEquals(Files.readAllBytes(firstMetadata), Files.readAllBytes(secondMetadata));
        String metadata = Files.readString(firstMetadata);
        assertTrue(metadata.contains("\"expected_error\": \"CORRUPT_DOCUMENT\""));
        assertTrue(metadata.contains("hwpx/table-footnote.hwpx"));
        assertTrue(metadata.contains(Hashing.sha256(firstRoot.resolve("hwp/simple.hwp"))));
        assertTrue(metadata.contains("\"fixture_license_spdx\": \"CC0-1.0\""));
    }

    @Test
    void runtimeCliEmitsExactlyOneJsonLineAndNoStderr() throws Exception {
        Path fixture = tempDir.resolve("simple.hwp");
        FixtureGenerator.writeSimpleHwp(fixture);
        ByteArrayOutputStream stdoutBytes = new ByteArrayOutputStream();
        ByteArrayOutputStream stderrBytes = new ByteArrayOutputStream();
        int status;
        try (PrintStream stdout = new PrintStream(stdoutBytes, true, StandardCharsets.UTF_8);
                PrintStream stderr = new PrintStream(stderrBytes, true, StandardCharsets.UTF_8)) {
            status = Main.run(
                    new String[] {
                        "--input", fixture.toString(),
                        "--media", "HWP",
                        "--profile-hash", PROFILE_HASH
                    },
                    stdout,
                    stderr);
        }
        String output = stdoutBytes.toString(StandardCharsets.UTF_8);
        assertEquals(0, status);
        assertEquals(1, output.lines().count());
        assertTrue(output.contains("\"ok\":true"));
        assertTrue(output.contains("\"name\":\"hwplib\""));
        assertTrue(output.contains("\"text_fingerprint\":"));
        assertTrue(output.contains("회의 사전 브리핑"));
        assertEquals("", stderrBytes.toString(StandardCharsets.UTF_8));
    }

    @Test
    void normalizationPreservesWhitespaceAndRejectsMalformedUnicode() throws Exception {
        assertEquals("  é\n", TextNormalization.normalize("  e\u0301\r\n"));
        RecordCollector collector = new RecordCollector();
        ExtractionFailure failure = assertThrows(
                ExtractionFailure.class,
                () -> collector.add(
                        RecordKind.PARAGRAPH,
                        String.valueOf((char) 0xd800),
                        Locator.paragraph(0, 0)));
        assertEquals("CORRUPT_DOCUMENT", failure.code());
    }
}
