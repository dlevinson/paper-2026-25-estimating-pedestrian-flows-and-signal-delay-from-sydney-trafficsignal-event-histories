import au.com.scats.hst.model.HstSiteModel;
import au.com.scats.hst.model.Statistics;
import au.com.scats.hst.runnable.HstSiteModelBuilder;
import org.eclipse.core.runtime.NullProgressMonitor;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

public class PedSignalGroupMapper {
    private static class Site {
        int site;
        String street1;
        String street2;
        String suburb;
        String region;
    }

    private static class StatSig {
        int frequency;
        long minimum;
        long maximum;
        long total;

        StatSig(Statistics stats) {
            frequency = stats.getFrequency();
            minimum = stats.getMinimum();
            maximum = stats.getMaximum();
            total = stats.getTotal();
        }

        boolean sameAs(StatSig other) {
            return frequency == other.frequency
                    && minimum == other.minimum
                    && maximum == other.maximum
                    && total == other.total;
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("Usage: PedSignalGroupMapper <sites.csv> <hst-root> <yyyymmdd> <output.csv>");
            System.exit(2);
        }

        List<Site> sites = readSites(new File(args[0]));
        File hstRoot = new File(args[1]);
        String yyyymmdd = args[2];
        File output = new File(args[3]);

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(output))) {
            writer.write("site,region,street1,street2,suburb,hst_walk_movement,matched_signal_groups,match_count,match_status,ped_frequency,ped_min_s,ped_max_s,ped_total_s\n");
            int processed = 0;
            for (Site site : sites) {
                processed++;
                File hstFile = new File(new File(hstRoot, site.region), site.region + "_" + yyyymmdd + ".hst");
                if (!hstFile.exists()) {
                    continue;
                }
                try {
                    processSite(site, hstFile, writer);
                } catch (Throwable error) {
                    writer.write(String.format(
                            "%d,%s,%s,%s,%s,,,,error,,,,%s%n",
                            site.site,
                            csv(site.region),
                            csv(site.street1),
                            csv(site.street2),
                            csv(site.suburb),
                            csv(error.getClass().getSimpleName() + ": " + error.getMessage())));
                }
                if (processed % 50 == 0) {
                    System.err.println("mapped_sites=" + processed + " of " + sites.size());
                }
            }
        }

        System.out.println(output.getPath());
    }

    private static void processSite(Site site, File hstFile, BufferedWriter writer) throws Exception {
        HstSiteModelBuilder builder = new HstSiteModelBuilder(hstFile, site.site);
        builder.run(new NullProgressMonitor());
        if (!builder.getErrors().isEmpty()) {
            throw new IllegalStateException("Builder reported " + builder.getErrors().size() + " error(s)");
        }
        HstSiteModel model = (HstSiteModel) builder.getSiteModel();
        if (model == null) {
            throw new IllegalStateException("No site model");
        }

        List<Integer> pedNumbers = new ArrayList<>(model.getPedsMap().keySet());
        Collections.sort(pedNumbers);
        List<Integer> signalGroups = new ArrayList<>(model.getSignalGroupsMap().keySet());
        Collections.sort(signalGroups);

        for (int pedNumber : pedNumbers) {
            Statistics pedStats = model.getPedStats(pedNumber, null, null);
            if (pedStats.getFrequency() <= 0) {
                continue;
            }
            StatSig pedSig = new StatSig(pedStats);
            List<Integer> matches = new ArrayList<>();
            for (int sg : signalGroups) {
                Statistics sgStats = model.getSignalGroupStats(sg, null, null);
                if (sgStats.getFrequency() <= 0) {
                    continue;
                }
                if (pedSig.sameAs(new StatSig(sgStats))) {
                    matches.add(sg);
                }
            }

            String status;
            if (matches.isEmpty()) {
                status = "no_match";
            } else if (matches.size() == 1) {
                status = "unique";
            } else {
                status = "multiple";
            }

            writer.write(String.format(
                    "%d,%s,%s,%s,%s,%d,%s,%d,%s,%d,%d,%d,%d%n",
                    site.site,
                    csv(site.region),
                    csv(site.street1),
                    csv(site.street2),
                    csv(site.suburb),
                    pedNumber,
                    csv(joinInts(matches)),
                    matches.size(),
                    csv(status),
                    pedStats.getFrequency(),
                    pedStats.getMinimum(),
                    pedStats.getMaximum(),
                    pedStats.getTotal()));
        }
    }

    private static List<Site> readSites(File sitesCsv) throws Exception {
        List<Site> result = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(sitesCsv))) {
            String header = reader.readLine();
            if (header == null || !header.startsWith("TCS_NO,")) {
                throw new IllegalArgumentException("Unexpected site CSV header");
            }
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) {
                    continue;
                }
                String[] cols = line.split(",", -1);
                if (cols.length < 8) {
                    continue;
                }
                Site site = new Site();
                site.site = Integer.parseInt(cols[0].trim());
                site.street1 = cols[1].trim();
                site.street2 = cols[2].trim();
                site.suburb = cols[3].trim();
                site.region = cols[5].trim().replaceFirst("^SR_", "");
                result.add(site);
            }
        }
        return result;
    }

    private static String joinInts(List<Integer> values) {
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < values.size(); i++) {
            if (i > 0) {
                builder.append(";");
            }
            builder.append(values.get(i));
        }
        return builder.toString();
    }

    private static String csv(String value) {
        if (value == null) {
            return "";
        }
        boolean quote = value.contains(",") || value.contains("\"") || value.contains("\n") || value.contains("\r");
        String escaped = value.replace("\"", "\"\"");
        return quote ? "\"" + escaped + "\"" : escaped;
    }
}
