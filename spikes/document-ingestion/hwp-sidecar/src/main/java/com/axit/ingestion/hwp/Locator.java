package com.axit.ingestion.hwp;

record Locator(
        int section,
        int paragraph,
        Integer table,
        Integer tableBlock,
        Integer tableRow,
        Integer cell,
        Integer cellParagraph,
        Integer footnote,
        Integer footnoteParagraph) {

    Locator {
        if (section < 0 || paragraph < 0) {
            throw new IllegalArgumentException("base locator indexes must be non-negative");
        }
        boolean hasTable = table != null
                || tableBlock != null
                || tableRow != null
                || cell != null
                || cellParagraph != null;
        boolean completeTable = table != null
                && tableBlock != null
                && tableRow != null
                && cell != null
                && cellParagraph != null;
        boolean hasFootnote = footnote != null || footnoteParagraph != null;
        boolean completeFootnote = footnote != null && footnoteParagraph != null;
        if (hasTable != completeTable || hasFootnote != completeFootnote || (hasTable && hasFootnote)) {
            throw new IllegalArgumentException("locator extension must be complete and exclusive");
        }
        if (hasTable && (table < 0 || tableBlock < 0 || tableRow < 0 || cell < 0 || cellParagraph < 0)) {
            throw new IllegalArgumentException("table locator indexes must be non-negative");
        }
        if (hasFootnote && (footnote < 0 || footnoteParagraph < 0)) {
            throw new IllegalArgumentException("footnote locator indexes must be non-negative");
        }
    }

    static Locator paragraph(int section, int paragraph) {
        return new Locator(section, paragraph, null, null, null, null, null, null, null);
    }

    static Locator tableCell(
            int section,
            int paragraph,
            int table,
            int tableBlock,
            int tableRow,
            int cell,
            int cellParagraph) {
        return new Locator(
                section,
                paragraph,
                table,
                tableBlock,
                tableRow,
                cell,
                cellParagraph,
                null,
                null);
    }

    static Locator footnote(
            int section,
            int paragraph,
            int footnote,
            int footnoteParagraph) {
        return new Locator(
                section,
                paragraph,
                null,
                null,
                null,
                null,
                null,
                footnote,
                footnoteParagraph);
    }
}
