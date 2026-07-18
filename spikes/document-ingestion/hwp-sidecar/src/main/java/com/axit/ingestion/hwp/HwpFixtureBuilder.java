package com.axit.ingestion.hwp;

import java.nio.file.Files;
import java.nio.file.Path;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.Section;
import kr.dogfoot.hwplib.object.bodytext.control.ControlAutoNumber;
import kr.dogfoot.hwplib.object.bodytext.control.ControlFootnote;
import kr.dogfoot.hwplib.object.bodytext.control.ControlTable;
import kr.dogfoot.hwplib.object.bodytext.control.ControlType;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.CtrlHeaderGso;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.autonumber.NumberSort;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.HeightCriterion;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.HorzRelTo;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.ObjectNumberSort;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.RelativeArrange;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.TextFlowMethod;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.TextHorzArrange;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.VertRelTo;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.gso.WidthCriterion;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.sectiondefine.TextDirection;
import kr.dogfoot.hwplib.object.bodytext.control.gso.textbox.LineChange;
import kr.dogfoot.hwplib.object.bodytext.control.gso.textbox.TextVerticalAlignment;
import kr.dogfoot.hwplib.object.bodytext.control.sectiondefine.NumberShape;
import kr.dogfoot.hwplib.object.bodytext.control.table.Cell;
import kr.dogfoot.hwplib.object.bodytext.control.table.DivideAtPageBoundary;
import kr.dogfoot.hwplib.object.bodytext.control.table.ListHeaderForCell;
import kr.dogfoot.hwplib.object.bodytext.control.table.Row;
import kr.dogfoot.hwplib.object.bodytext.control.table.Table;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.object.bodytext.paragraph.charshape.ParaCharShape;
import kr.dogfoot.hwplib.object.bodytext.paragraph.header.ParaHeader;
import kr.dogfoot.hwplib.object.bodytext.paragraph.lineseg.LineSegItem;
import kr.dogfoot.hwplib.object.bodytext.paragraph.lineseg.ParaLineSeg;
import kr.dogfoot.hwplib.object.bodytext.paragraph.text.HWPCharControlExtend;
import kr.dogfoot.hwplib.object.bodytext.paragraph.text.ParaText;
import kr.dogfoot.hwplib.tool.blankfilemaker.BlankFileMaker;
import kr.dogfoot.hwplib.writer.HWPWriter;

final class HwpFixtureBuilder {
    static final String SIMPLE_TEXT = "회의 사전 브리핑은 안건과 참가자 근거를 함께 제시합니다.";
    static final String TABLE_BODY_TEXT = "회의 후속 조치 표와 검토 기준 각주";
    static final String FOOTNOTE_TEXT = "검토 기준일: 2026-07-18";
    static final String[][] TABLE_TEXT = {
        {"항목", "담당"},
        {"후속 과제", "후속 담당: 민서"}
    };

    private HwpFixtureBuilder() {}

    static void writeSimple(Path output) throws Exception {
        HWPFile document = BlankFileMaker.make();
        firstParagraph(document).getText().addString(SIMPLE_TEXT);
        write(document, output);
    }

    static void writeTableAndFootnote(Path output) throws Exception {
        HWPFile document = BlankFileMaker.make();
        Paragraph host = firstParagraph(document);
        host.getText().addString(TABLE_BODY_TEXT);
        addTable(document, host);
        addFootnote(host);
        write(document, output);
    }

    private static Paragraph firstParagraph(HWPFile document) {
        Section section = document.getBodyText().getSectionList().get(0);
        return section.getParagraph(0);
    }

    private static void write(HWPFile document, Path output) throws Exception {
        Files.createDirectories(output.toAbsolutePath().normalize().getParent());
        HWPWriter.toFile(document, output.toString());
    }

    private static void addTable(HWPFile document, Paragraph host) throws Exception {
        addExtendedControlCharacter(host.getText(), (short) 0x000b, new byte[] {' ', 'l', 'b', 't'});
        ControlTable control = (ControlTable) host.addNewControl(ControlType.Table);
        configureTableHeader(control.getHeader());

        Table table = control.getTable();
        table.getProperty().setDivideAtPageBoundary(DivideAtPageBoundary.DivideByCell);
        table.getProperty().setAutoRepeatTitleRow(false);
        table.setRowCount(2);
        table.setColumnCount(2);
        table.setCellSpacing(0);
        table.setLeftInnerMargin(0);
        table.setRightInnerMargin(0);
        table.setTopInnerMargin(0);
        table.setBottomInnerMargin(0);
        table.setBorderFillId(1);
        table.getCellCountOfRowList().add(2);
        table.getCellCountOfRowList().add(2);

        for (int rowIndex = 0; rowIndex < TABLE_TEXT.length; rowIndex++) {
            Row row = control.addNewRow();
            for (int cellIndex = 0; cellIndex < TABLE_TEXT[rowIndex].length; cellIndex++) {
                Cell cell = row.addNewCell();
                configureCellHeader(cell.getListHeader(), cellIndex, rowIndex);
                configureParagraph(
                        cell.getParagraphList().addNewParagraph(), TABLE_TEXT[rowIndex][cellIndex]);
            }
        }
    }

    private static void configureTableHeader(CtrlHeaderGso header) {
        header.getProperty().setLikeWord(false);
        header.getProperty().setApplyLineSpace(false);
        header.getProperty().setVertRelTo(VertRelTo.Para);
        header.getProperty().setVertRelativeArrange(RelativeArrange.TopOrLeft);
        header.getProperty().setHorzRelTo(HorzRelTo.Para);
        header.getProperty().setHorzRelativeArrange(RelativeArrange.TopOrLeft);
        header.getProperty().setVertRelToParaLimit(false);
        header.getProperty().setAllowOverlap(false);
        header.getProperty().setWidthCriterion(WidthCriterion.Absolute);
        header.getProperty().setHeightCriterion(HeightCriterion.Absolute);
        header.getProperty().setProtectSize(false);
        header.getProperty().setTextFlowMethod(TextFlowMethod.FitWithText);
        header.getProperty().setTextHorzArrange(TextHorzArrange.BothSides);
        header.getProperty().setObjectNumberSort(ObjectNumberSort.Table);
        header.setxOffset(mmToHwp(20));
        header.setyOffset(mmToHwp(20));
        header.setWidth(mmToHwp(100));
        header.setHeight(mmToHwp(60));
        header.setzOrder(0);
        header.setOutterMarginLeft(0);
        header.setOutterMarginRight(0);
        header.setOutterMarginTop(0);
        header.setOutterMarginBottom(0);
    }

    private static void configureCellHeader(
            ListHeaderForCell header, int columnIndex, int rowIndex) {
        header.setParaCount(1);
        header.getProperty().setTextDirection(TextDirection.Horizontal);
        header.getProperty().setLineChange(LineChange.Normal);
        header.getProperty().setTextVerticalAlignment(TextVerticalAlignment.Center);
        header.getProperty().setProtectCell(false);
        header.getProperty().setEditableAtFormMode(false);
        header.setColIndex(columnIndex);
        header.setRowIndex(rowIndex);
        header.setColSpan(1);
        header.setRowSpan(1);
        header.setWidth(mmToHwp(50));
        header.setHeight(mmToHwp(30));
        header.setLeftMargin(0);
        header.setRightMargin(0);
        header.setTopMargin(0);
        header.setBottomMargin(0);
        header.setBorderFillId(1);
        header.setTextWidth(mmToHwp(50));
        header.setFieldName("");
    }

    private static void addFootnote(Paragraph host) throws Exception {
        addExtendedControlCharacter(host.getText(), (short) 0x0011, new byte[] {' ', ' ', 'n', 'f'});
        ControlFootnote footnote = (ControlFootnote) host.addNewControl(ControlType.Footnote);
        footnote.getHeader().setNumber(1);
        footnote.getHeader().setNumberShape(NumberShape.Number);
        footnote.getListHeader().getProperty().setTextDirection(TextDirection.Horizontal);
        footnote.getListHeader().getProperty().setLineChange(LineChange.Normal);
        footnote.getListHeader().getProperty().setTextVerticalAlignment(TextVerticalAlignment.Top);

        Paragraph note = footnote.getParagraphList().addNewParagraph();
        configureParagraph(note, "");
        addExtendedControlCharacter(note.getText(), (short) 0x0012, new byte[] {'o', 'n', 't', 'a'});
        ControlAutoNumber number = (ControlAutoNumber) note.addNewControl(ControlType.AutoNumber);
        number.getHeader().getProperty().setNumberSort(NumberSort.FootNote);
        number.getHeader().getProperty().setNumberShape(NumberShape.Number);
        number.getHeader().getProperty().setSuperScript(true);
        number.getHeader().setNumber(1);
        note.getText().addString(FOOTNOTE_TEXT);
    }

    private static void configureParagraph(Paragraph paragraph, String text) throws Exception {
        ParaHeader header = paragraph.getHeader();
        header.setLastInList(true);
        header.setParaShapeId(1);
        header.setStyleId((short) 1);
        header.getDivideSort().setDivideSection(false);
        header.getDivideSort().setDivideMultiColumn(false);
        header.getDivideSort().setDividePage(false);
        header.getDivideSort().setDivideColumn(false);
        header.setCharShapeCount(1);
        header.setRangeTagCount(0);
        header.setLineAlignCount(1);
        header.setInstanceID(0);
        header.setIsMergedByTrack(0);

        paragraph.createText();
        paragraph.getText().addString(text);
        paragraph.createCharShape();
        ParaCharShape charShape = paragraph.getCharShape();
        charShape.addParaCharShape(0, 1);
        paragraph.createLineSeg();
        ParaLineSeg lineSeg = paragraph.getLineSeg();
        LineSegItem item = lineSeg.addNewLineSegItem();
        item.setTextStartPosition(0);
        item.setLineVerticalPosition(0);
        item.setLineHeight(1000);
        item.setTextPartHeight(1000);
        item.setDistanceBaseLineToLineVerticalPosition(850);
        item.setLineSpace(300);
        item.setStartPositionFromColumn(0);
        item.setSegmentWidth((int) mmToHwp(50));
        item.getTag().setFirstSegmentAtLine(true);
        item.getTag().setLastSegmentAtLine(true);
    }

    private static void addExtendedControlCharacter(
            ParaText text, short code, byte[] controlIdLittleEndian) throws Exception {
        HWPCharControlExtend marker = text.addNewExtendControlChar();
        marker.setCode(code);
        byte[] addition = new byte[12];
        System.arraycopy(controlIdLittleEndian, 0, addition, 0, controlIdLittleEndian.length);
        marker.setAddition(addition);
        text.addString("");
    }

    private static long mmToHwp(double millimeters) {
        return (long) (millimeters * 72000.0 / 254.0 + 0.5);
    }
}
