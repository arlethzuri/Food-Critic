"""Fixed safety-overview charts, computed directly (not by the agent) and
shared across dashboard variants."""
import plotly.express as px
import streamlit as st


def render_overview(con):
    col1, col2 = st.columns(2)

    with col1:
        df_scores = con.execute("""
            SELECT inspection_score AS score
            FROM inspections
            WHERE inspection_score IS NOT NULL
        """).fetchdf()
        st.plotly_chart(
            px.histogram(df_scores, x="score", nbins=30, title="Inspection score distribution"),
            use_container_width=True,
        )

    with col2:
        df_types = con.execute("""
            SELECT violation_phr AS category, COUNT(*) AS n
            FROM violations
            WHERE violation_phr IS NOT NULL AND violation_phr != ''
            GROUP BY 1 ORDER BY n DESC LIMIT 10
        """).fetchdf()
        st.plotly_chart(
            px.bar(df_types, x="n", y="category", orientation="h", title="Top 10 violation categories"),
            use_container_width=True,
        )

    col3, col4 = st.columns(2)

    with col3:
        df_trend = con.execute("""
            SELECT strftime(i.inspection_date, '%Y') AS year,
                   COUNT(*) FILTER (WHERE vc.critical) AS critical,
                   COUNT(*) FILTER (WHERE NOT vc.critical) AS noncritical
            FROM inspections i
            JOIN violations v ON v.inspection_id = i.inspection_id
            JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
            GROUP BY 1 ORDER BY 1
        """).fetchdf()
        df_trend_long = df_trend.melt(id_vars="year", value_vars=["critical", "noncritical"],
                                       var_name="severity", value_name="count")
        st.plotly_chart(
            px.line(df_trend_long, x="year", y="count", color="severity", title="Violations per year by severity"),
            use_container_width=True,
        )

    with col4:
        df_type = con.execute("""
            SELECT establishment_type, COUNT(*) AS n
            FROM establishment_keys
            WHERE establishment_type IS NOT NULL
            GROUP BY 1 ORDER BY n DESC LIMIT 10
        """).fetchdf()
        st.plotly_chart(
            px.bar(df_type, x="n", y="establishment_type", orientation="h", title="Establishments by type (top 10)"),
            use_container_width=True,
        )
