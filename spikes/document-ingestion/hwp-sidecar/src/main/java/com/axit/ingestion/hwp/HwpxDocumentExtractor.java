package com.axit.ingestion.hwp;

import java.nio.file.Path;
import kr.dogfoot.hwpxlib.object.HWPXFile;
import kr.dogfoot.hwpxlib.object.content.section_xml.SectionXMLFile;
import kr.dogfoot.hwpxlib.object.content.section_xml.SubList;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.Ctrl;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.CtrlItem;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.Para;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.Run;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.RunItem;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.T;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.TItem;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.ctrl.EndNote;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.ctrl.FootNote;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.Table;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.table.Tc;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.table.Tr;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.t.FWSpace;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.t.Hyphen;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.t.LineBreak;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.t.NBSpace;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.t.NormalText;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.t.Tab;
import kr.dogfoot.hwpxlib.reader.HWPXReader;

final class HwpxDocumentExtractor {
    private HwpxDocumentExtractor() {}

    static void extract(Path input, RecordCollector collector) throws Exception {
        HWPXFile document = HWPXReader.fromFile(input.toFile(), true);
        int sectionIndex = 0;
        for (SectionXMLFile section : document.sectionXMLFileList().items()) {
            int paragraphIndex = 0;
            for (Para paragraph : section.paras()) {
                extractParagraph(paragraph, sectionIndex, paragraphIndex, collector);
                paragraphIndex++;
            }
            sectionIndex++;
        }
    }

    private static void extractParagraph(
            Para paragraph,
            int section,
            int paragraphIndex,
            RecordCollector collector)
            throws ExtractionFailure {
        collector.add(
                RecordKind.PARAGRAPH,
                paragraphText(paragraph),
                Locator.paragraph(section, paragraphIndex));

        int tableIndex = 0;
        int footnoteIndex = 0;
        for (int runIndex = 0; runIndex < paragraph.countOfRun(); runIndex++) {
            Run run = paragraph.getRun(runIndex);
            for (RunItem item : run.runItems()) {
                if (item instanceof Table table) {
                    extractTable(
                            table,
                            section,
                            paragraphIndex,
                            tableIndex++,
                            runIndex,
                            collector);
                } else if (item instanceof Ctrl ctrl) {
                    for (CtrlItem ctrlItem : ctrl.ctrlItems()) {
                        if (ctrlItem instanceof FootNote footnote) {
                            extractFootnote(
                                    footnote,
                                    section,
                                    paragraphIndex,
                                    footnoteIndex++,
                                    collector);
                        } else if (ctrlItem instanceof EndNote) {
                            collector.warn("UNSUPPORTED_ENDNOTE");
                        }
                    }
                }
            }
        }
    }

    private static void extractTable(
            Table table,
            int section,
            int paragraph,
            int tableIndex,
            int tableBlock,
            RecordCollector collector)
            throws ExtractionFailure {
        int rowIndex = 0;
        for (Tr row : table.trs()) {
            int cellIndex = 0;
            for (Tc cell : row.tcs()) {
                SubList cellContent = cell.subList();
                if (cellContent != null) {
                    int cellParagraph = 0;
                    for (Para nested : cellContent.paras()) {
                        collector.add(
                                RecordKind.TABLE_CELL,
                                paragraphText(nested),
                                Locator.tableCell(
                                        section,
                                        paragraph,
                                        tableIndex,
                                        tableBlock,
                                        rowIndex,
                                        cellIndex,
                                        cellParagraph));
                        if (hasStructuredItems(nested)) {
                            collector.warn("NESTED_CONTROL_SKIPPED");
                        }
                        cellParagraph++;
                    }
                }
                cellIndex++;
            }
            rowIndex++;
        }
    }

    private static void extractFootnote(
            FootNote footnote,
            int section,
            int paragraph,
            int footnoteIndex,
            RecordCollector collector)
            throws ExtractionFailure {
        if (footnote.subList() == null) {
            return;
        }
        int noteParagraph = 0;
        for (Para nested : footnote.subList().paras()) {
            collector.add(
                    RecordKind.FOOTNOTE,
                    paragraphText(nested),
                    Locator.footnote(section, paragraph, footnoteIndex, noteParagraph));
            noteParagraph++;
        }
    }

    private static boolean hasStructuredItems(Para paragraph) {
        for (Run run : paragraph.runs()) {
            for (RunItem item : run.runItems()) {
                if (item instanceof Table || item instanceof Ctrl) {
                    return true;
                }
            }
        }
        return false;
    }

    private static String paragraphText(Para paragraph) {
        StringBuilder text = new StringBuilder();
        for (Run run : paragraph.runs()) {
            for (RunItem item : run.runItems()) {
                if (item instanceof T value) {
                    appendText(value, text);
                }
            }
        }
        return text.toString();
    }

    private static void appendText(T value, StringBuilder output) {
        if (value.isOnlyText()) {
            output.append(value.onlyText());
            return;
        }
        if (value.isEmpty()) {
            return;
        }
        for (TItem item : value.items()) {
            if (item instanceof NormalText normal) {
                if (normal.text() != null) {
                    output.append(normal.text());
                }
            } else if (item instanceof Tab) {
                output.append('\t');
            } else if (item instanceof LineBreak) {
                output.append('\n');
            } else if (item instanceof NBSpace) {
                output.append('\u00a0');
            } else if (item instanceof FWSpace) {
                output.append('\u3000');
            } else if (item instanceof Hyphen) {
                output.append('-');
            }
        }
    }
}
