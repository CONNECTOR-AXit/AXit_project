package com.axit.ingestion.hwp;

import java.text.Normalizer;

final class TextNormalization {
    private TextNormalization() {}

    static String normalize(String input) {
        if (input == null) {
            return "";
        }
        String lineNormalized = input.replace("\r\n", "\n").replace('\r', '\n');
        return Normalizer.normalize(lineNormalized, Normalizer.Form.NFC);
    }

    static boolean hasValidSurrogates(String value) {
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            if (Character.isHighSurrogate(current)) {
                if (index + 1 >= value.length()
                        || !Character.isLowSurrogate(value.charAt(index + 1))) {
                    return false;
                }
                index++;
            } else if (Character.isLowSurrogate(current)) {
                return false;
            }
        }
        return true;
    }
}
