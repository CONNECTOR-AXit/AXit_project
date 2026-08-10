package com.axit.ingestion.hwp;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Arrays;

final class DocumentExtractor {
    // Keep the sidecar boundary aligned with policy.v1.json and the upload API.
    private static final long MAX_INPUT_BYTES = 200L * 1024L * 1024L;
    private static final byte[] CFB_MAGIC = new byte[] {
        (byte) 0xd0, (byte) 0xcf, 0x11, (byte) 0xe0,
        (byte) 0xa1, (byte) 0xb1, 0x1a, (byte) 0xe1
    };
    private static final byte[] ZIP_LOCAL_MAGIC = new byte[] {'P', 'K', 0x03, 0x04};

    private DocumentExtractor() {}

    static ExtractionEnvelope extract(Path input, MediaType mediaType, String profileHash)
            throws ExtractionFailure {
        validateInput(input, profileHash);
        verifyMagic(input, mediaType);
        String sourceSha256 = hashInput(input);

        RecordCollector collector = new RecordCollector();
        ParserMetadata parser;
        try {
            parser = switch (mediaType) {
                case HWP -> {
                    HwpDocumentExtractor.extract(input, collector);
                    yield new ParserMetadata("hwplib", "1.1.10");
                }
                case HWPX -> {
                    HwpxPreflight.verify(input);
                    HwpxDocumentExtractor.extract(input, collector);
                    yield new ParserMetadata("hwpxlib", "1.0.9");
                }
            };
        } catch (ExtractionFailure failure) {
            throw failure;
        } catch (Exception parserFailure) {
            if (mediaType == MediaType.HWP
                    && "Files with passwords are not supported.".equals(parserFailure.getMessage())) {
                throw ExtractionFailure.of(
                        "ENCRYPTED_DOCUMENT",
                        "Encrypted documents are not accepted by the ingestion spike.");
            }
            if (System.getenv("AXIT_HWP_DEBUG") != null) {
                parserFailure.printStackTrace();
            }
            throw ExtractionFailure.of(
                    "CORRUPT_DOCUMENT",
                    "The document parser could not safely read this input.");
        }

        if (collector.records().isEmpty()) {
            collector.warn("NO_EXTRACTABLE_TEXT");
        }
        try {
            if (!sourceSha256.equals(Hashing.sha256(input))) {
                throw ExtractionFailure.of(
                        "INPUT_READ_FAILED", "The input changed while it was being parsed.");
            }
            return new ExtractionEnvelope(
                    sourceSha256,
                    profileHash,
                    parser,
                    collector.records(),
                    collector.warnings());
        } catch (IOException failure) {
            throw ExtractionFailure.of("INPUT_READ_FAILED", "The input file could not be read.");
        }
    }

    private static String hashInput(Path input) throws ExtractionFailure {
        try {
            return Hashing.sha256(input);
        } catch (IOException | SecurityException failure) {
            throw ExtractionFailure.of("INPUT_READ_FAILED", "The input file could not be read.");
        }
    }

    private static void validateInput(Path input, String profileHash) throws ExtractionFailure {
        if (!Hashing.isSha256(profileHash)) {
            throw ExtractionFailure.of(
                    "INVALID_PROFILE_HASH",
                    "The extraction profile identity must be a lowercase SHA-256 value.");
        }
        try {
            if (!Files.isRegularFile(input, LinkOption.NOFOLLOW_LINKS)) {
                throw ExtractionFailure.of("INVALID_INPUT", "The input must be one regular file.");
            }
            long size = Files.size(input);
            if (size == 0 || size > MAX_INPUT_BYTES) {
                throw ExtractionFailure.of(
                        "INPUT_SIZE_REJECTED",
                        "The input file is empty or exceeds the approved size bound.");
            }
        } catch (ExtractionFailure failure) {
            throw failure;
        } catch (IOException | SecurityException failure) {
            throw ExtractionFailure.of("INPUT_READ_FAILED", "The input file could not be read.");
        }
    }

    private static void verifyMagic(Path input, MediaType mediaType) throws ExtractionFailure {
        byte[] expected = mediaType == MediaType.HWP ? CFB_MAGIC : ZIP_LOCAL_MAGIC;
        try {
            byte[] prefix;
            try (InputStream stream = Files.newInputStream(input)) {
                prefix = stream.readNBytes(expected.length);
            }
            if (!Arrays.equals(prefix, expected)) {
                throw ExtractionFailure.of(
                        "TYPE_MISMATCH",
                        "The input does not match the declared document type.");
            }
        } catch (ExtractionFailure failure) {
            throw failure;
        } catch (IOException | SecurityException failure) {
            throw ExtractionFailure.of("INPUT_READ_FAILED", "The input file could not be read.");
        }
    }
}
