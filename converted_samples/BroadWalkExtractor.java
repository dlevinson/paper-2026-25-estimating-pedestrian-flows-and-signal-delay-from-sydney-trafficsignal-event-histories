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
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class BroadWalkExtractor {
    private static final int SECONDS_PER_DAY = 86400;

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

    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("Usage: BroadWalkExtractor <sites.csv> <hst-root> <yyyymmdd> <output-dir>");
            System.exit(2);
        }

        File sitesCsv = new File(args[0]);
        File hstRoot = new File(args[1]);
        String yyyymmdd = args[2];
        File outputDir = new File(args[3]);
        outputDir.mkdirs();

        List<Site> sites = readSites(sitesCsv);
        File observationsFile = new File(outputDir, "walk_delay_observations_" + yyyymmdd + ".csv");
        File censoredFile = new File(outputDir, "walk_censored_intervals_" + yyyymmdd + ".csv");
        File statusFile = new File(outputDir, "site_processing_status_" + yyyymmdd + ".csv");

        try (
                BufferedWriter observations = new BufferedWriter(new FileWriter(observationsFile));
                BufferedWriter censored = new BufferedWriter(new FileWriter(censoredFile));
                BufferedWriter status = new BufferedWriter(new FileWriter(statusFile))
        ) {
            observations.write("site,region,street1,street2,suburb,lon,lat,movement,acceptance_start_s,acceptance_start_time,demand_on_s,demand_on_time,delay_s,hour,same_second,event_summary\n");
            censored.write("site,region,street1,street2,suburb,lon,lat,movement,acceptance_start_s,acceptance_start_time,censor_s,censor_time,censored_wait_s,hour,censor_reason,event_summary\n");
            status.write("site,region,street1,street2,suburb,lon,lat,status,points,walk_event_points,observations,censored,error\n");

            int processed = 0;
            for (Site site : sites) {
                processed++;
                File hstFile = new File(new File(hstRoot, site.region), site.region + "_" + yyyymmdd + ".hst");
                if (!hstFile.exists()) {
                    writeStatus(status, site, "missing_hst", 0, 0, 0, 0, hstFile.getPath());
                    continue;
                }

                try {
                    SiteCounts counts = processSite(site, hstFile, observations, censored);
                    writeStatus(status, site, "ok", counts.points, counts.walkEventPoints, counts.observations, counts.censored, "");
                } catch (Throwable error) {
                    writeStatus(status, site, "error", 0, 0, 0, 0, error.getClass().getSimpleName() + ": " + error.getMessage());
                    error.printStackTrace(System.err);
                }

                if (processed % 25 == 0) {
                    System.err.println("processed_sites=" + processed + " of " + sites.size());
                }
            }
        }

        System.out.println(observationsFile.getPath());
        System.out.println(censoredFile.getPath());
        System.out.println(statusFile.getPath());
    }

    private static class SiteCounts {
        int points;
        int walkEventPoints;
        int observations;
        int censored;
    }

    private static SiteCounts processSite(Site site, File hstFile, BufferedWriter observations, BufferedWriter censored) throws Exception {
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
                        writeCensored(censored, site, change.movement, model, state.acceptStart, state.acceptStartTime, t, time, "active_on", summary);
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
                            writeObservation(observations, site, change.movement, model, state.acceptStart, state.acceptStartTime, t, time, delay, summary);
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
                writeCensored(censored, site, entry.getKey(), model, state.acceptStart, state.acceptStartTime, maxT, maxTime, "end_of_file", "");
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
                "%d,%s,%s,%s,%s,%.6f,%.6f,%d,%d,%s,%d,%s,%d,%d,%s,%s%n",
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
                "%d,%s,%s,%s,%s,%.6f,%.6f,%d,%d,%s,%d,%s,%d,%d,%s,%s%n",
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
            Site site,
            String processingStatus,
            int points,
            int walkEventPoints,
            int observations,
            int censored,
            String error) throws Exception {
        out.write(String.format(
                "%d,%s,%s,%s,%s,%.6f,%.6f,%s,%d,%d,%d,%d,%s%n",
                site.site,
                csv(site.region),
                csv(site.street1),
                csv(site.street2),
                csv(site.suburb),
                site.lon,
                site.lat,
                csv(processingStatus),
                points,
                walkEventPoints,
                observations,
                censored,
                csv(error)));
    }

    private static int secondOfDay(HstSiteModel model, long t) {
        long seconds;
        if (model.hasV5OrOlderEvents()) {
            seconds = (t - model.getTStartOfDay()) % SECONDS_PER_DAY;
        } else {
            ZonedDateTime zdt = ZonedDateTime.ofInstant(Instant.ofEpochSecond(t), model.getTimeZone().toZoneId());
            seconds = zdt.toLocalTime().toSecondOfDay();
        }
        if (seconds < 0) {
            seconds += SECONDS_PER_DAY;
        }
        return (int) seconds;
    }

    private static String hms(int secondOfDay) {
        int hour = secondOfDay / 3600;
        int minute = (secondOfDay % 3600) / 60;
        int second = secondOfDay % 60;
        return String.format("%02d:%02d:%02d", hour, minute, second);
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
