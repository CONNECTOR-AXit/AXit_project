package com.axit.ingestion.hwp;

final class ExtractionFailure extends Exception {
    private static final long serialVersionUID = 1L;

    private final String code;
    private final String publicMessage;

    private ExtractionFailure(String code, String publicMessage) {
        super(code, null, false, false);
        this.code = code;
        this.publicMessage = publicMessage;
    }

    static ExtractionFailure of(String code, String publicMessage) {
        if (code == null || !code.matches("[A-Z][A-Z0-9_]*")) {
            throw new IllegalArgumentException("failure code must be uppercase snake case");
        }
        if (publicMessage == null || publicMessage.isBlank() || publicMessage.contains("\n")) {
            throw new IllegalArgumentException("failure message must be a safe single line");
        }
        return new ExtractionFailure(code, publicMessage);
    }

    String code() {
        return code;
    }

    String publicMessage() {
        return publicMessage;
    }

    String toJson() {
        return "{\"error\":{\"code\":"
                + JsonWriter.quote(code)
                + ",\"message\":"
                + JsonWriter.quote(publicMessage)
                + ",\"retryable\":false},\"ok\":false}";
    }
}
