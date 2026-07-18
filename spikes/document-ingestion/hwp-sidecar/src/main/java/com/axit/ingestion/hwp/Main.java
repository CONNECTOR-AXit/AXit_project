package com.axit.ingestion.hwp;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

public final class Main {
    private static final int MAX_JSON_BYTES = 1024 * 1024;

    private Main() {}

    public static void main(String[] args) {
        int status = run(args, System.out, System.err);
        if (status != 0) {
            System.exit(status);
        }
    }

    static int run(String[] args, PrintStream stdout, PrintStream stderr) {
        try {
            if (args.length > 0 && args[0].equals("generate")) {
                return generate(args, stdout);
            }
            Map<String, String> options = parseOptions(args, 0);
            requireExactly(options, "--input", "--media", "--profile-hash");
            MediaType mediaType = parseMedia(options.get("--media"));
            Path input = safePath(options.get("--input"));
            ExtractionEnvelope envelope = DocumentExtractor.extract(
                    input, mediaType, options.get("--profile-hash"));
            return emit(stdout, envelope.toJson(), 0);
        } catch (ExtractionFailure failure) {
            return emit(stdout, failure.toJson(), 2);
        } catch (Exception failure) {
            return emit(
                    stdout,
                    ExtractionFailure.of(
                                    "INTERNAL_ERROR",
                                    "The sidecar failed without exposing parser or input details.")
                            .toJson(),
                    2);
        }
    }

    private static int generate(String[] args, PrintStream stdout) throws Exception {
        Map<String, String> options = parseOptions(args, 1);
        if (!options.containsKey("--output-root")) {
            throw ExtractionFailure.of(
                    "INVALID_ARGUMENTS", "Fixture generation requires an output root.");
        }
        for (String option : options.keySet()) {
            if (!option.equals("--output-root") && !option.equals("--metadata")) {
                throw ExtractionFailure.of(
                        "INVALID_ARGUMENTS", "Fixture generation received an unsupported option.");
            }
        }
        Path outputRoot = safePath(options.get("--output-root"));
        Path metadata = options.containsKey("--metadata")
                ? safePath(options.get("--metadata"))
                : Path.of("spikes/document-ingestion/fixture_sources/hwp/generated-fixtures.json");
        FixtureGenerator.generate(outputRoot, metadata);
        return emit(stdout, "{\"generated\":5,\"ok\":true}", 0);
    }

    private static Map<String, String> parseOptions(String[] args, int offset)
            throws ExtractionFailure {
        if ((args.length - offset) % 2 != 0) {
            throw ExtractionFailure.of(
                    "INVALID_ARGUMENTS", "The sidecar requires option-value pairs.");
        }
        Map<String, String> options = new LinkedHashMap<>();
        for (int index = offset; index < args.length; index += 2) {
            String key = args[index];
            String value = args[index + 1];
            if (!key.startsWith("--") || value.isEmpty() || options.put(key, value) != null) {
                throw ExtractionFailure.of(
                        "INVALID_ARGUMENTS", "The sidecar received malformed or duplicate options.");
            }
        }
        return options;
    }

    private static void requireExactly(Map<String, String> options, String... required)
            throws ExtractionFailure {
        if (options.size() != required.length) {
            throw ExtractionFailure.of(
                    "INVALID_ARGUMENTS", "The sidecar received missing or unsupported options.");
        }
        for (String option : required) {
            if (!options.containsKey(option)) {
                throw ExtractionFailure.of(
                        "INVALID_ARGUMENTS", "The sidecar received missing or unsupported options.");
            }
        }
    }

    private static MediaType parseMedia(String media) throws ExtractionFailure {
        try {
            return MediaType.valueOf(media);
        } catch (IllegalArgumentException failure) {
            throw ExtractionFailure.of(
                    "UNSUPPORTED_MEDIA_TYPE", "Only HWP and HWPX media selectors are accepted.");
        }
    }

    private static Path safePath(String value) throws ExtractionFailure {
        try {
            return Path.of(value).toAbsolutePath().normalize();
        } catch (InvalidPathException | SecurityException failure) {
            throw ExtractionFailure.of("INVALID_INPUT", "The supplied file path is invalid.");
        }
    }

    private static int emit(PrintStream output, String json, int status) {
        String bounded = json;
        if (json.getBytes(StandardCharsets.UTF_8).length > MAX_JSON_BYTES) {
            bounded = ExtractionFailure.of(
                            "OUTPUT_LIMIT_EXCEEDED",
                            "The sidecar JSON exceeds the approved output bound.")
                    .toJson();
            status = 2;
        }
        byte[] encoded = bounded.getBytes(StandardCharsets.UTF_8);
        output.write(encoded, 0, encoded.length);
        output.write('\n');
        output.flush();
        return status;
    }
}
