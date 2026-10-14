import au.com.scats.base.tuple.IntPair;
import au.com.scats.file.hst.event.Event;
import au.com.scats.file.hst.event.WalkEvent;
import au.com.scats.file.hst.event.WalkEventData;
import au.com.scats.file.hst.event.WalkV5Event;
import au.com.scats.file.hst.event.WalkV5EventData;
import au.com.scats.file.hst.event.WalkV5EventDataState;
import au.com.scats.hst.model.HstSiteModel;
import au.com.scats.hst.model.point.EventPoint;
import au.com.scats.hst.runnable.HstSiteModelBuilder;
import au.com.scats.time.Point;
import org.eclipse.core.runtime.NullProgressMonitor;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class SelectedMultiDateWalkExtractor {
    private static class Site {
        int site;
        String street1;
        String street2;
        String suburb;
        String region;
        double lon;
        double lat;
    }

    private static class WalkState {
        Boolean active = null;
        Boolean demand = null;
        Long acceptStart = null;
        String acceptStartTime = "";
    }

    private static class StatusChange {
        int movement;
        boolean activeOn;
        boolean activeOff;
        boolean demandOn;
        boolean demandOff;
    }

    private static class SiteCounts {
        int points;
        int walkEventPoints;
        int observations;
        int censored;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("Usage: SelectedMultiDateWalkExtractor <sites.csv> <hst-root> <dates.txt> <output-dir>");
            System.exit(2);
        }

        File sitesCsv = new File(args[0]);
        File hstRoot = new File(args[1]);
        File datesTxt = new File(args[2]);
        File outputDir = new File(args[3]);
        outputDir.mkdirs();

        List<Site> sites = readSites(sitesCsv);
        List<String> dates = readDates(datesTxt);

        File observationsFile = new File(outputDir, "calibration_walk_delay_observations.csv");
        File censoredFile = new File(outputDir, "calibration_walk_censored_intervals.csv");
        File statusFile = new File(outputDir, "calibration_site_processing_status.csv");

        try (
                BufferedWriter observations = new BufferedWriter(new FileWriter(observationsFile));
                BufferedWriter censored = new BufferedWriter(new FileWriter(censoredFile));
                BufferedWriter status = new BufferedWriter(new FileWriter(statusFile))
        ) {
            observations.write("date,period,site,region,street1,street2,suburb,lon,lat,movement,acceptance_start_s,acceptance_start_time,demand_on_s,demand_on_time,delay_s,hour,same_second,event_summary\n");
            censored.write("date,period,site,region,street1,street2,suburb,lon,lat,movement,acceptance_start_s,acceptance_start_time,censor_s,censor_time,censored_wait_s,hour,censor_reason,event_summary\n");
            status.write("date,period,site,region,street1,street2,suburb,lon,lat,status,points,walk_event_points,observations,censored,error\n");

            int processed = 0;
            for (String date : dates) {
                String period = period(date);
                for (Site site : sites) {
                    processed++;
                    File hstFile = new File(new File(hstRoot, site.region), site.region + "_" + date + ".hst");
                    if (!hstFile.exists()) {
                        writeStatus(status, date, period, site, "missing_hst", 0, 0, 0, 0, hstFile.getPath());
                        continue;
                    }

                    try {
                        SiteCounts counts = processSite(date, period, site, hstFile, observations, censored);
                        writeStatus(status, date, period, site, "ok", counts.points, counts.walkEventPoints, counts.observations, counts.censored, "");
                    } catch (Throwable error) {
                        writeStatus(status, date, period, site, "error", 0, 0, 0, 0, error.getClass().getSimpleName() + ": " + error.getMessage());
                        error.printStackTrace(System.err);
                    }
                }
                if (processed % 30 == 0) {
                    System.err.println("processed_site_dates=" + processed + " of " + (dates.size() * sites.size()));
                }
            }
        }

        System.out.println(observationsFile.getPath());
        System.out.println(censoredFile.getPath());
        System.out.println(statusFile.getPath());
    }

    private static SiteCounts processSite(String date, String period, Site site, File hstFile, BufferedWriter observations, BufferedWriter censored) throws Exception {
        HstSiteModelBuilder builder = new HstSiteModelBuilder(hstFile, site.site);
        builder.run(new NullProgressMonitor());
        if (!builder.getErrors().isEmpty()) {
            throw new IllegalStateException("Builder reported " + builder.getErrors().size() + " error(s)");
        }

        HstSiteModel model = (HstSiteModel) builder.getSiteModel();
        if (model == null) {
            throw new IllegalStateException("No site model");
        }

        SiteCounts counts = new SiteCounts();
        counts.points = model.getPoints().size();
        Map<Integer, WalkState> states = new HashMap<>();

        for (Point point : model.getPoints()) {
            if (!(point instanceof EventPoint)) {
                continue;
            }
            Event event = ((EventPoint) point).getEvent();
            List<StatusChange> changes = walkStatusChanges(event);
            if (changes.isEmpty()) {
                continue;
            }
            counts.walkEventPoints++;

            long t = point.getTime();
            int secondOfDay = secondOfDay(model, t);
            String time = hms(secondOfDay);
            String summary = event.getSummary();

            for (StatusChange change : changes) {
                WalkState state = states.computeIfAbsent(change.movement, key -> new WalkState());

                if (change.activeOn) {
                    if (state.acceptStart != null) {
                        writeCensored(censored, date, period, site, change.movement, model, state.acceptStart, state.acceptStartTime, t, time, "active_on", summary);
                        counts.censored++;
                    }
                    state.active = true;
                    state.acceptStart = null;
                    state.acceptStartTime = "";
                }

                if (change.activeOff) {
                    state.active = false;
                    state.acceptStart = t;
                    state.acceptStartTime = time;
                }

                if (change.demandOff) {
                    state.demand = false;
                }

                if (change.demandOn) {
                    if (Boolean.FALSE.equals(state.active) && state.acceptStart != null) {
                        long delay = t - state.acceptStart;
                        if (delay >= 0) {
                            writeObservation(observations, date, period, site, change.movement, model, state.acceptStart, state.acceptStartTime, t, time, delay, summary);
                            counts.observations++;
                        }
                        state.acceptStart = null;
                        state.acceptStartTime = "";
                    }
                    state.demand = true;
                }
            }
        }

        long maxT = model.getMaxT();
        String maxTime = hms(secondOfDay(model, maxT));
        for (Map.Entry<Integer, WalkState> entry : states.entrySet()) {
            WalkState state = entry.getValue();
            if (state.acceptStart != null && maxT > state.acceptStart) {
                writeCensored(censored, date, period, site, entry.getKey(), model, state.acceptStart, state.acceptStartTime, maxT, maxTime, "end_of_file", "");
                counts.censored++;
            }
        }

        return counts;
    }

    private static List<StatusChange> walkStatusChanges(Event event) {
        List<StatusChange> result = new ArrayList<>();
        if (event instanceof WalkEvent) {
            for (WalkEventData data : ((WalkEvent) event).getWalkStatuses()) {
                StatusChange change = new StatusChange();
                change.movement = data.walkNumber;
                for (IntPair state : data.states) {
                    if (state.val1 == 1 && state.val2 == 1) change.demandOn = true;
                    if (state.val1 == 1 && state.val2 == 0) change.demandOff = true;
                    if (state.val1 == 2 && state.val2 == 1) change.activeOn = true;
                    if (state.val1 == 2 && state.val2 == 0) change.activeOff = true;
                }
                result.add(change);
            }
        } else if (event instanceof WalkV5Event) {
            for (WalkV5EventData data : ((WalkV5Event) event).getWalkStatuses()) {
                StatusChange change = new StatusChange();
                change.movement = data.walkNumber;
                for (WalkV5EventDataState state : data.states) {
                    if (state.subtype == 1 && state.state == 1) change.demandOn = true;
                    if (state.subtype == 1 && state.state == 0) change.demandOff = true;
                    if (state.subtype == 2 && state.state == 1) change.activeOn = true;
                    if (state.subtype == 2 && state.state != 1) change.activeOff = true;
                }
                result.add(change);
            }
        }
        return result;
    }

    private static void writeObservation(
            BufferedWriter out,
            String date,
            String period,
            Site site,
            int movement,
            HstSiteModel model,
            long acceptStart,
            String acceptStartTime,
            long demandOn,
            String demandOnTime,
            long delay,
            String summary) throws Exception {
        int hour = secondOfDay(model, acceptStart) / 3600;
        out.write(String.format(
                "%s,%s,%d,%s,%s,%s,%s,%.6f,%.6f,%d,%d,%s,%d,%s,%d,%d,%s,%s%n",
                csv(date),
                csv(period),
                site.site,
                csv(site.region),
                csv(site.street1),
                csv(site.street2),
                csv(site.suburb),
                site.lon,
                site.lat,
                movement,
                secondOfDay(model, acceptStart),
                csv(acceptStartTime),
                secondOfDay(model, demandOn),
                csv(demandOnTime),
                delay,
                hour,
                delay == 0 ? "yes" : "no",
                csv(summary)));
    }

    private static void writeCensored(
            BufferedWriter out,
            String date,
            String period,
            Site site,
            int movement,
            HstSiteModel model,
            long acceptStart,
            String acceptStartTime,
            long censor,
            String censorTime,
            String reason,
            String summary) throws Exception {
        long wait = censor - acceptStart;
        int hour = secondOfDay(model, acceptStart) / 3600;
        out.write(String.format(
                "%s,%s,%d,%s,%s,%s,%s,%.6f,%.6f,%d,%d,%s,%d,%s,%d,%d,%s,%s%n",
                csv(date),
                csv(period),
                site.site,
                csv(site.region),
                csv(site.street1),
                csv(site.street2),
                csv(site.suburb),
                site.lon,
                site.lat,
                movement,
                secondOfDay(model, acceptStart),
                csv(acceptStartTime),
                secondOfDay(model, censor),
                csv(censorTime),
                wait,
                hour,
                csv(reason),
                csv(summary)));
    }

    private static void writeStatus(
            BufferedWriter out,
            String date,
            String period,
            Site site,
            String status,
            int points,
            int walkPoints,
            int observations,
            int censored,
            String error) throws Exception {
        out.write(String.format(
                "%s,%s,%d,%s,%s,%s,%s,%.6f,%.6f,%s,%d,%d,%d,%d,%s%n",
                csv(date),
                csv(period),
                site.site,
                csv(site.region),
                csv(site.street1),
                csv(site.street2),
                csv(site.suburb),
                site.lon,
                site.lat,
                csv(status),
                points,
                walkPoints,
                observations,
                censored,
                csv(error)));
    }

    private static List<Site> readSites(File sitesCsv) throws Exception {
        List<Site> sites = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(sitesCsv))) {
            String header = reader.readLine();
            if (header == null) return sites;
            String line;
            while ((line = reader.readLine()) != null) {
                String[] parts = parseCsvLine(line);
                if (parts.length < 8) continue;
                Site site = new Site();
                site.site = Integer.parseInt(parts[0].trim());
                site.street1 = parts[1].trim();
                site.street2 = parts[2].trim();
                site.suburb = parts[3].trim();
                site.region = parts[5].trim().replaceFirst("^SR_", "");
                site.lon = Double.parseDouble(parts[6].trim());
                site.lat = Double.parseDouble(parts[7].trim());
                sites.add(site);
            }
        }
        return sites;
    }

    private static List<String> readDates(File datesTxt) throws Exception {
        List<String> dates = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(datesTxt))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String date = line.trim();
                if (date.isEmpty() || date.startsWith("#")) continue;
                dates.add(date);
            }
        }
        return dates;
    }

    private static String[] parseCsvLine(String line) {
        List<String> values = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < line.length(); i++) {
            char ch = line.charAt(i);
            if (ch == '"') {
                if (quoted && i + 1 < line.length() && line.charAt(i + 1) == '"') {
                    current.append('"');
                    i++;
                } else {
                    quoted = !quoted;
                }
            } else if (ch == ',' && !quoted) {
                values.add(current.toString());
                current.setLength(0);
            } else {
                current.append(ch);
            }
        }
        values.add(current.toString());
        return values.toArray(new String[0]);
    }

    private static int secondOfDay(HstSiteModel model, long timestamp) {
        return (int) Math.floorMod(timestamp - model.getMinT(), 86400);
    }

    private static String hms(int seconds) {
        int value = Math.floorMod(seconds, 86400);
        int hour = value / 3600;
        int minute = (value % 3600) / 60;
        int second = value % 60;
        return String.format("%02d:%02d:%02d", hour, minute, second);
    }

    private static String period(String yyyymmdd) {
        int year = Integer.parseInt(yyyymmdd.substring(0, 4));
        int month = Integer.parseInt(yyyymmdd.substring(4, 6));
        int day = Integer.parseInt(yyyymmdd.substring(6, 8));
        int weekday = LocalDate.of(year, month, day).getDayOfWeek().getValue();
        return weekday <= 5 ? "weekday" : "weekend";
    }

    private static String csv(String value) {
        if (value == null) return "";
        boolean quote = value.contains(",") || value.contains("\"") || value.contains("\n") || value.contains("\r");
        String escaped = value.replace("\"", "\"\"");
        return quote ? "\"" + escaped + "\"" : escaped;
    }
}
