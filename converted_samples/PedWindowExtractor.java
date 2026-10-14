import au.com.scats.hst.model.HstSiteModel;
import au.com.scats.hst.model.interval.PedInterval;
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

public class PedWindowExtractor {
    private static class Site {
        int site;
        String street1;
        String street2;
        String suburb;
        String region;
        double lon;
        double lat;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("Usage: PedWindowExtractor <sites.csv> <hst-root> <yyyymmdd> <output.csv>");
            System.exit(2);
        }

        List<Site> sites = readSites(new File(args[0]));
        File hstRoot = new File(args[1]);
        String yyyymmdd = args[2];
        File output = new File(args[3]);

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(output))) {
            writer.write("site,region,street1,street2,suburb,lon,lat,movement,state,state_desc,start_s,end_s,duration_s\n");
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
                    error.printStackTrace(System.err);
                }
                if (processed % 50 == 0) {
                    System.err.println("window_sites=" + processed + " of " + sites.size());
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

        List<Integer> movements = new ArrayList<>(model.getPedsMap().keySet());
        Collections.sort(movements);
        for (int movement : movements) {
            List<PedInterval> intervals = model.getPedsMap().get(movement);
            if (intervals == null) {
                continue;
            }
            for (PedInterval interval : intervals) {
                long duration = interval.getDuration();
                if (duration <= 0) {
                    continue;
                }
                writer.write(String.format(
                        "%d,%s,%s,%s,%s,%.6f,%.6f,%d,%d,%s,%d,%d,%d%n",
                        site.site,
                        csv(site.region),
                        csv(site.street1),
                        csv(site.street2),
                        csv(site.suburb),
                        site.lon,
                        site.lat,
                        movement,
                        interval.getState(),
                        csv(interval.getStateDesc()),
                        secondOfDay(model, interval.getStart()),
                        secondOfDay(model, interval.getEnd()),
                        duration));
            }
        }
    }

    private static int secondOfDay(HstSiteModel model, long t) {
        long seconds = (t - model.getTStartOfDay()) % 86400;
        if (seconds < 0) {
            seconds += 86400;
        }
        return (int) seconds;
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
                site.lon = parseDouble(cols[6]);
                site.lat = parseDouble(cols[7]);
                result.add(site);
            }
        }
        return result;
    }

    private static double parseDouble(String value) {
        try {
            return Double.parseDouble(value.trim());
        } catch (Exception error) {
            return Double.NaN;
        }
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
