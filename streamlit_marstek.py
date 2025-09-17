from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, HoverTool, DatetimeTickFormatter, Legend
from bokeh.palettes import Category10, Category20
from bokeh.layouts import column
from bokeh.models.tools import ResetTool
import math

def plot_bokeh_soc(plot_df):
    # Ensure time_local is datetime (tz-aware). Bokeh wants naive datetimes in ms UTC;
    # we'll convert to UTC milliseconds since epoch for consistency.
    # But since we want to display local tz labels, we'll format ticks accordingly using DatetimeTickFormatter.
    df = plot_df.copy()
    # Convert to naive UTC datetimes in milliseconds (Bokeh accepts ms epoch)
    # We'll also keep the display strings in local timezone for hover.
    df["time_utc_ms"] = (pd.to_datetime(df["time_local"]).astype("datetime64[ns]") .view("int64") // 1_000_000)
    df["time_str_local"] = pd.to_datetime(df["time_local"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    # Determine unique devices and palette
    devices = df["device_id"].unique().tolist()
    n = len(devices)
    if n <= 10:
        palette = Category10[max(3, n)]
    else:
        palette = Category20[ min(20, n) ]

    # Create figure
    p = figure(
        x_axis_type="datetime",
        sizing_mode="stretch_width",
        height=360,
        toolbar_location="below",      # toolbar appears below the plot
        tools="pan,wheel_zoom,box_zoom,reset,save",  # available tools
        active_drag="pan",
    )

    # Configure axes and formatting (show local time ticks)
    p.xaxis.formatter = DatetimeTickFormatter(
        hours=["%H:%M"],
        days=["%d %b"],
        months=["%b %Y"],
        years=["%Y"]
    )
    p.xaxis.major_label_orientation = math.pi/4
    p.yaxis.axis_label = "State of Charge (%)"
    p.y_range.start = 0
    p.y_range.end = 100
    p.grid.grid_line_alpha = 0.25

    # Add HoverTool (show local time string and SOC)
    hover = HoverTool(
        tooltips=[
            ("Time (local)", "@time_str_local"),
            ("Device", "@device_id"),
            ("SOC", "@soc{0.0}%"),
        ],
        mode="vline"
    )
    p.add_tools(hover)

    # Build lines for each device
    legend_items = []
    for i, dev in enumerate(devices):
        dev_df = df[df["device_id"] == dev].sort_values("time_utc_ms")
        if dev_df.empty:
            continue
        source = ColumnDataSource(data={
            "x": dev_df["time_utc_ms"],
            "soc": dev_df["soc"],
            "time_str_local": dev_df["time_str_local"],
            "device_id": dev_df["device_id"],
        })
        color = palette[i % len(palette)]
        r = p.line("x", "soc", source=source, line_width=2.5, color=color, alpha=0.9)
        p.circle("x", "soc", source=source, size=4, color=color, alpha=0.9)
        legend_items.append((str(dev), [r]))

    # Create a Legend and place it below the plot, centered
    if legend_items:
        legend = Legend(items=legend_items, location="center")
        legend.click_policy = "hide"  # allow tap to hide traces
        # place legend below by putting it in a column layout under the figure
        # Bokeh's Legend can also be placed inside plot (location), but we want it below visually.

        # The recommended way: build a column with the plot and then an empty widget space with the legend rendered below.
        # Add legend as a separate layout element
        # However Bokeh doesn't render Legend as standalone widget easily; we'll set legend location to "below"
        p.add_layout(legend, 'below')

    # Tidy toolbar: optionally remove some buttons via CSS or Bokeh config is limited.
    # Bokeh's toolbar is rendered below by toolbar_location="below"

    return p

# Usage in Streamlit:
from bokeh.embed import components
from bokeh.resources import CDN
p = plot_bokeh_soc(plot_df)
st.bokeh_chart(p, use_container_width=True)
