package com.axit.ingestion.hwp;

enum MediaType {
    HWP("application/x-hwp"),
    HWPX("application/x-hwpx");

    private final String value;

    MediaType(String value) {
        this.value = value;
    }

    String value() {
        return value;
    }

    static MediaType parse(String value) throws ExtractionFailure {
        for (MediaType candidate : values()) {
            if (candidate.value.equals(value)) {
                return candidate;
            }
        }
        throw ExtractionFailure.of(
                "UNSUPPORTED_MEDIA_TYPE",
                "Only the approved HWP and HWPX media types are accepted.");
    }
}
