package com.axit.ingestion.hwp;

import java.nio.file.Files;
import java.nio.file.Path;
import kr.dogfoot.hwpxlib.object.HWPXFile;
import kr.dogfoot.hwpxlib.object.content.section_xml.SubList;
import kr.dogfoot.hwpxlib.object.content.context_hpf.Meta;
import kr.dogfoot.hwpxlib.object.content.section_xml.enumtype.TablePageBreak;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.Ctrl;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.Para;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.Run;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.RunItem;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.T;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.ctrl.FootNote;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.Table;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.table.Tc;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.table.Tr;
import kr.dogfoot.hwpxlib.tool.blankfilemaker.BlankFileMaker;
import kr.dogfoot.hwpxlib.writer.HWPXWriter;

final class HwpxFixtureBuilder {
    static final String SIMPLE_TEXT = "회의 안건과 근거를 HWPX 문단에서 확인합니다.";
    static final String TABLE_BODY_TEXT = "HWPX 후속 조치 표와 검토 기준 각주";
    static final String FOOTNOTE_TEXT = "HWPX 검토 기준일: 2026-07-18";
    static final String[][] TABLE_TEXT = {
        {"항목", "담당"},
        {"후속 과제", "HWPX 후속 담당: 지윤"}
    };

    private HwpxFixtureBuilder() {}

    static void writeSimple(Path output) throws Exception {
        HWPXFile document = BlankFileMaker.make();
        fixGeneratedMetadata(document);
        Para paragraph = document.sectionXMLFileList().get(0).getPara(0);
        T text = firstText(paragraph);
        text.addText(SIMPLE_TEXT);

        write(document, output);
    }

    static void writeTableAndFootnote(Path output) throws Exception {
        HWPXFile document = BlankFileMaker.make();
        fixGeneratedMetadata(document);
        Para paragraph = document.sectionXMLFileList().get(0).getPara(0);
        firstText(paragraph).addText(TABLE_BODY_TEXT);
        addTable(paragraph);
        addFootnote(paragraph);

        write(document, output);
    }

    private static void write(HWPXFile document, Path output) throws Exception {
        Files.createDirectories(output.toAbsolutePath().normalize().getParent());
        Path libraryOutput = output.resolveSibling(output.getFileName() + ".hwpxlib.tmp");
        Files.deleteIfExists(libraryOutput);
        HWPXWriter.toFilepath(document, libraryOutput.toString());
        try {
            DeterministicZip.rewrite(libraryOutput, output);
        } finally {
            Files.deleteIfExists(libraryOutput);
        }
    }

    private static void addTable(Para host) {
        Table table = firstRun(host).addNewTable();
        table.id("axit-hwpx-table-0");
        table.zOrder(0);
        table.pageBreak(TablePageBreak.CELL);
        table.repeatHeader(false);
        table.rowCnt((short) TABLE_TEXT.length);
        table.colCnt((short) TABLE_TEXT[0].length);
        table.cellSpacing(0);
        table.borderFillIDRef("1");
        table.noAdjust(false);
        table.createInMargin();
        table.inMargin().set(0L, 0L, 0L, 0L);

        for (int rowIndex = 0; rowIndex < TABLE_TEXT.length; rowIndex++) {
            Tr row = table.addNewTr();
            for (int cellIndex = 0; cellIndex < TABLE_TEXT[rowIndex].length; cellIndex++) {
                addCell(row, rowIndex, cellIndex, TABLE_TEXT[rowIndex][cellIndex]);
            }
        }
    }

    private static void addCell(Tr row, int rowIndex, int cellIndex, String text) {
        Tc cell = row.addNewTc();
        cell.name("axit-cell-" + rowIndex + '-' + cellIndex);
        cell.header(rowIndex == 0);
        cell.hasMargin(true);
        cell.protect(false);
        cell.editable(true);
        cell.dirty(false);
        cell.borderFillIDRef("1");
        cell.createCellAddr();
        cell.cellAddr().colAddr((short) cellIndex);
        cell.cellAddr().rowAddr((short) rowIndex);
        cell.createCellSpan();
        cell.cellSpan().colSpan((short) 1);
        cell.cellSpan().rowSpan((short) 1);
        cell.createCellSz();
        cell.cellSz().set(21260L, 5670L);
        cell.createCellMargin();
        cell.cellMargin().set(0L, 0L, 0L, 0L);
        cell.createSubList();

        SubList content = cell.subList();
        content.id("axit-table-" + rowIndex + '-' + cellIndex);
        content.textWidth(21260);
        content.textHeight(5670);
        addTextParagraph(content, "axit-table-p-" + rowIndex + '-' + cellIndex, text);
    }

    private static void addFootnote(Para host) {
        Ctrl control = firstRun(host).addNewCtrl();
        FootNote footnote = control.addNewFootNote();
        footnote.number(1);
        footnote.suffixChar(")");
        footnote.instId("axit-footnote-0");
        footnote.createSubList();
        footnote.subList().id("axit-footnote-list-0");
        addTextParagraph(footnote.subList(), "axit-footnote-p-0", FOOTNOTE_TEXT);
    }

    private static void addTextParagraph(SubList content, String id, String text) {
        Para paragraph = content.addNewPara();
        paragraph.id(id);
        paragraph.paraPrIDRef("3");
        paragraph.styleIDRef("0");
        paragraph.pageBreak(false);
        paragraph.columnBreak(false);
        paragraph.merged(false);
        Run run = paragraph.addNewRun();
        run.charPrIDRef("0");
        run.addNewT().addText(text);
    }

    private static void fixGeneratedMetadata(HWPXFile document) {
        for (Meta meta : document.contentHPFFile().metaData().metas()) {
            if (meta.name().equals("CreatedDate") || meta.name().equals("ModifiedDate")) {
                meta.text("2026-07-18T00:00:00Z");
            } else if (meta.name().equals("date")) {
                meta.text("2026-07-18");
            }
        }
    }

    private static T firstText(Para paragraph) {
        for (Run run : paragraph.runs()) {
            for (RunItem item : run.runItems()) {
                if (item instanceof T text) {
                    return text;
                }
            }
        }
        return paragraph.addNewRun().addNewT();
    }

    private static Run firstRun(Para paragraph) {
        for (Run run : paragraph.runs()) {
            return run;
        }
        Run run = paragraph.addNewRun();
        run.charPrIDRef("0");
        return run;
    }
}
