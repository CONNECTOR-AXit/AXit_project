package com.axit.ingestion.hwp;

import java.nio.file.Path;
import java.util.List;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.Section;
import kr.dogfoot.hwplib.object.bodytext.control.Control;
import kr.dogfoot.hwplib.object.bodytext.control.ControlFootnote;
import kr.dogfoot.hwplib.object.bodytext.control.ControlTable;
import kr.dogfoot.hwplib.object.bodytext.control.ControlType;
import kr.dogfoot.hwplib.object.bodytext.control.table.Cell;
import kr.dogfoot.hwplib.object.bodytext.control.table.Row;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.reader.HWPReader;

final class HwpDocumentExtractor {
    private HwpDocumentExtractor() {}

    static void extract(Path input, RecordCollector collector) throws Exception {
        HWPFile document = HWPReader.fromFile(input.toFile());
        List<Section> sections = document.getBodyText().getSectionList();
        for (int sectionIndex = 0; sectionIndex < sections.size(); sectionIndex++) {
            Section section = sections.get(sectionIndex);
            for (int paragraphIndex = 0;
                    paragraphIndex < section.getParagraphCount();
                    paragraphIndex++) {
                extractParagraph(
                        section.getParagraph(paragraphIndex),
                        sectionIndex,
                        paragraphIndex,
                        collector);
            }
        }
    }

    private static void extractParagraph(
            Paragraph paragraph,
            int section,
            int paragraphIndex,
            RecordCollector collector)
            throws Exception {
        collector.add(
                RecordKind.PARAGRAPH,
                paragraph.getNormalString(),
                Locator.paragraph(section, paragraphIndex));

        List<Control> controls = paragraph.getControlList();
        if (controls == null) {
            return;
        }
        int tableIndex = 0;
        int footnoteIndex = 0;
        for (Control control : controls) {
            if (control instanceof ControlTable table) {
                extractTable(table, section, paragraphIndex, tableIndex++, collector);
            } else if (control instanceof ControlFootnote footnote) {
                extractFootnote(
                        footnote,
                        section,
                        paragraphIndex,
                        footnoteIndex++,
                        collector);
            } else if (control.getType() == ControlType.Endnote) {
                collector.warn("UNSUPPORTED_ENDNOTE");
            }
        }
    }

    private static void extractTable(
            ControlTable table,
            int section,
            int paragraph,
            int tableIndex,
            RecordCollector collector)
            throws Exception {
        List<Row> rows = table.getRowList();
        for (int rowIndex = 0; rowIndex < rows.size(); rowIndex++) {
            List<Cell> cells = rows.get(rowIndex).getCellList();
            for (int cellIndex = 0; cellIndex < cells.size(); cellIndex++) {
                Cell cell = cells.get(cellIndex);
                for (int cellParagraph = 0;
                        cellParagraph < cell.getParagraphList().getParagraphCount();
                        cellParagraph++) {
                    Paragraph nested = cell.getParagraphList().getParagraph(cellParagraph);
                    collector.add(
                            RecordKind.TABLE_CELL,
                            nested.getNormalString(),
                            Locator.tableCell(
                                    section,
                                    paragraph,
                                    tableIndex,
                                    0,
                                    rowIndex,
                                    cellIndex,
                                    cellParagraph));
                    if (nested.getControlList() != null && !nested.getControlList().isEmpty()) {
                        collector.warn("NESTED_CONTROL_SKIPPED");
                    }
                }
            }
        }
    }

    private static void extractFootnote(
            ControlFootnote footnote,
            int section,
            int paragraph,
            int footnoteIndex,
            RecordCollector collector)
            throws Exception {
        for (int noteParagraph = 0;
                noteParagraph < footnote.getParagraphList().getParagraphCount();
                noteParagraph++) {
            Paragraph nested = footnote.getParagraphList().getParagraph(noteParagraph);
            collector.add(
                    RecordKind.FOOTNOTE,
                    nested.getNormalString(),
                    Locator.footnote(section, paragraph, footnoteIndex, noteParagraph));
        }
    }
}
