package com.axit.ingestion.hwp;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipFile;

final class HwpxPreflight {
    private static final byte[] MEDIA_MARKER =
            "application/hwp+zip".getBytes(StandardCharsets.US_ASCII);
    private static final int MAX_ENTRIES = 256;
    // These limits mirror policy.v1.json; the outer sandbox still enforces them.
    private static final long MAX_ENTRY_BYTES = 200L * 1024L * 1024L;
    private static final long MAX_XML_BYTES = 8L * 1024L * 1024L;
    private static final long MAX_TOTAL_BYTES = 512L * 1024L * 1024L;
    private static final long MAX_COMPRESSION_RATIO = 100L;

    private HwpxPreflight() {}

    static void verify(Path input) throws ExtractionFailure {
        try (ZipFile zip = new ZipFile(input.toFile(), StandardCharsets.UTF_8)) {
            Set<String> names = new HashSet<>();
            long totalDeclared = 0;
            long totalRead = 0;
            int entryCount = 0;
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                entryCount++;
                if (entryCount > MAX_ENTRIES) {
                    throw failure(
                            "ARCHIVE_LIMIT_EXCEEDED",
                            "The HWPX package contains too many archive entries.");
                }
                String name = entry.getName();
                validatePath(name);
                if (!names.add(name)) {
                    throw failure(
                            "ARCHIVE_DUPLICATE_ENTRY",
                            "The HWPX package contains duplicate archive entries.");
                }
                if (entry.isDirectory()) {
                    continue;
                }
                long declared = entry.getSize();
                long compressed = entry.getCompressedSize();
                if (declared < 0 || compressed < 0) {
                    throw failure(
                            "CORRUPT_ARCHIVE",
                            "The HWPX package has incomplete archive metadata.");
                }
                if (declared > MAX_ENTRY_BYTES || totalDeclared + declared > MAX_TOTAL_BYTES) {
                    throw failure(
                            "ARCHIVE_LIMIT_EXCEEDED",
                            "The expanded HWPX package exceeds the approved size bound.");
                }
                if (isXml(name) && declared > MAX_XML_BYTES) {
                    throw failure(
                            "ARCHIVE_LIMIT_EXCEEDED",
                            "An HWPX XML entry exceeds the approved size bound.");
                }
                totalDeclared += declared;
                if (exceedsCompressionRatio(declared, compressed)) {
                    throw failure(
                            "ARCHIVE_RATIO_REJECTED",
                            "The HWPX package exceeds the approved compression-ratio bound.");
                }
                long actual = scanEntry(
                        zip, entry, declared, isXml(name), name.equals("mimetype"));
                if (totalRead + actual > MAX_TOTAL_BYTES) {
                    throw failure(
                            "ARCHIVE_LIMIT_EXCEEDED",
                            "The expanded HWPX package exceeds the approved size bound.");
                }
                totalRead += actual;
            }
            if (!names.contains("mimetype")) {
                throw failure("TYPE_MISMATCH", "The HWPX package is missing its media marker.");
            }
        } catch (ExtractionFailure failure) {
            throw failure;
        } catch (ZipException failure) {
            throw failure("CORRUPT_ARCHIVE", "The HWPX package is not a valid ZIP archive.");
        } catch (IOException | SecurityException failure) {
            throw failure("INPUT_READ_FAILED", "The HWPX package could not be safely read.");
        }
    }

    static boolean exceedsCompressionRatio(long expandedBytes, long compressedBytes) {
        return expandedBytes > 0
                && (compressedBytes == 0
                        || expandedBytes > compressedBytes * MAX_COMPRESSION_RATIO);
    }

    private static void validatePath(String name) throws ExtractionFailure {
        if (name == null
                || name.isEmpty()
                || name.length() > 512
                || name.startsWith("/")
                || name.startsWith("\\")
                || name.contains("\\")
                || name.indexOf('\0') >= 0
                || name.indexOf(':') >= 0) {
            throw failure(
                    "ARCHIVE_PATH_REJECTED",
                    "The HWPX package contains an unsafe archive path.");
        }
        for (String component : name.split("/", -1)) {
            if (component.equals(".") || component.equals("..")) {
                throw failure(
                        "ARCHIVE_PATH_REJECTED",
                        "The HWPX package contains an unsafe archive path.");
            }
        }
    }

    private static boolean isXml(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        return lower.endsWith(".xml") || lower.endsWith(".hpf");
    }

    private static long scanEntry(
            ZipFile zip,
            ZipEntry entry,
            long declared,
            boolean xmlEntry,
            boolean mediaMarker)
            throws IOException, ExtractionFailure {
        ByteArrayOutputStream output = xmlEntry || mediaMarker
                ? new ByteArrayOutputStream((int) Math.min(declared, 8192))
                : null;
        long readTotal = 0;
        try (InputStream input = zip.getInputStream(entry)) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) {
                readTotal += count;
                long activeLimit = xmlEntry ? MAX_XML_BYTES : MAX_ENTRY_BYTES;
                if (readTotal > activeLimit) {
                    throw failure(
                            "ARCHIVE_LIMIT_EXCEEDED",
                            "An expanded HWPX entry exceeds the approved size bound.");
                }
                if (output != null) {
                    output.write(buffer, 0, count);
                }
            }
            if (readTotal != declared) {
                throw failure(
                        "CORRUPT_ARCHIVE",
                        "An HWPX entry does not match its declared archive size.");
            }
        }
        if (mediaMarker && !Arrays.equals(output.toByteArray(), MEDIA_MARKER)) {
            throw failure(
                    "TYPE_MISMATCH",
                    "The HWPX package has an invalid media marker.");
        }
        if (!xmlEntry) {
            return readTotal;
        }
        String xml;
        try {
            xml = StandardCharsets.UTF_8
                    .newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(java.nio.ByteBuffer.wrap(output.toByteArray()))
                    .toString();
        } catch (CharacterCodingException invalidEncoding) {
            throw failure(
                    "XML_ENCODING_REJECTED",
                    "HWPX XML entries must use the approved UTF-8 encoding.");
        }
        String upper = xml.toUpperCase(Locale.ROOT);
        if (upper.indexOf('\0') >= 0) {
            throw failure(
                    "XML_ENCODING_REJECTED",
                    "HWPX XML entries must not contain zero code points.");
        }
        if (upper.contains("<!DOCTYPE") || upper.contains("<!ENTITY")) {
            throw failure(
                    "XML_DTD_FORBIDDEN",
                    "DTD and entity declarations are forbidden in HWPX XML.");
        }
        return readTotal;
    }

    private static ExtractionFailure failure(String code, String message) {
        return ExtractionFailure.of(code, message);
    }
}
