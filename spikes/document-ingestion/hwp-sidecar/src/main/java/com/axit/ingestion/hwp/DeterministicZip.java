package com.axit.ingestion.hwp;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.CRC32;
import java.util.zip.Deflater;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

final class DeterministicZip {
    private static final LocalDateTime FIXED_TIMESTAMP = LocalDateTime.of(1980, 1, 1, 0, 0);

    private DeterministicZip() {}

    static void rewrite(Path source, Path output) throws IOException {
        Map<String, byte[]> entries = new LinkedHashMap<>();
        try (ZipFile zip = new ZipFile(source.toFile())) {
            var values = zip.entries();
            while (values.hasMoreElements()) {
                ZipEntry entry = values.nextElement();
                if (entry.isDirectory()) {
                    continue;
                }
                try (InputStream input = zip.getInputStream(entry)) {
                    if (entries.put(entry.getName(), input.readAllBytes()) != null) {
                        throw new IOException("duplicate generated ZIP entry");
                    }
                }
            }
        }
        write(entries, output);
    }

    static void write(Map<String, byte[]> entries, Path output) throws IOException {
        Files.createDirectories(output.toAbsolutePath().normalize().getParent());
        Path temporary = output.resolveSibling(output.getFileName() + ".deterministic.tmp");
        Files.deleteIfExists(temporary);
        List<String> names = new ArrayList<>(entries.keySet());
        names.sort(Comparator.comparingInt((String name) -> name.equals("mimetype") ? 0 : 1)
                .thenComparing(Comparator.naturalOrder()));
        try (OutputStream raw = Files.newOutputStream(temporary);
                ZipOutputStream zip = new ZipOutputStream(raw)) {
            zip.setLevel(Deflater.BEST_COMPRESSION);
            for (String name : names) {
                byte[] data = entries.get(name);
                ZipEntry entry = new ZipEntry(name);
                entry.setTimeLocal(FIXED_TIMESTAMP);
                if (name.equals("mimetype")) {
                    CRC32 crc = new CRC32();
                    crc.update(data);
                    entry.setMethod(ZipEntry.STORED);
                    entry.setSize(data.length);
                    entry.setCompressedSize(data.length);
                    entry.setCrc(crc.getValue());
                }
                zip.putNextEntry(entry);
                zip.write(data);
                zip.closeEntry();
            }
        }
        try {
            Files.move(
                    temporary,
                    output,
                    StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException unsupportedAtomicMove) {
            Files.move(temporary, output, StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
