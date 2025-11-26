"""Azure SSIS Package Component for Dagster.

This component allows you to execute SSIS packages deployed to Azure-SSIS Integration Runtime
directly from Dagster assets.
"""

import dagster as dg
import pyodbc
import time
import re
from typing import Optional
from enum import Enum


class SSISExecutionStatus(Enum):
    """SSIS package execution status codes from SSISDB catalog."""
    CREATED = 1
    RUNNING = 2
    CANCELED = 3
    FAILED = 4
    PENDING = 5
    ENDED_UNEXPECTEDLY = 6
    SUCCEEDED = 7
    STOPPING = 8
    COMPLETED = 9


class SsisPackage(dg.Component, dg.Model, dg.Resolvable):
    """Execute SSIS packages on Azure-SSIS Integration Runtime.

    This component creates a Dagster asset that triggers an SSIS package execution
    in Azure Data Factory, polls for completion, and captures execution statistics.

    Example YAML usage:
        type: ssis_package
        params:
          asset_key: load_lease_data
          sql_server: izzy-ssis-test.database.windows.net
          sql_database: SSISDB
          sql_username: sqladmin
          sql_password: your-password
          folder_name: IrvineDemo
          project_name: dagster-ssis-demo
          package_name: LoadLeaseData.dtsx
          poll_interval_sec: 5
          max_wait_time_sec: 600
          description: Loads Irvine Company lease data from CSV to Azure SQL
    """

    # SQL Server Configuration for SSISDB
    sql_server: str  # e.g., "izzy-ssis-test.database.windows.net"
    sql_database: str = "SSISDB"
    sql_username: str
    sql_password: str

    # SSIS Package Location
    folder_name: str  # e.g., "IrvineDemo"
    project_name: str  # e.g., "dagster-ssis-demo"
    package_name: str  # e.g., "LoadLeaseData.dtsx"

    # Dagster Asset Configuration
    asset_key: str
    description: Optional[str] = "Execute SSIS package on Azure-SSIS IR"
    group_name: Optional[str] = "ssis_integration"

    # Polling Configuration
    poll_interval_sec: int = 5
    max_wait_time_sec: int = 600

    @classmethod
    def get_spec(cls) -> dg.ComponentTypeSpec:
        return dg.ComponentTypeSpec(
            owners=["data-engineering@irvinecompany.com"],
            tags=["ssis", "azure", "etl"],
        )

    def build_defs(self, context: dg.ComponentLoadContext) -> dg.Definitions:
        """Build Dagster definitions for the SSIS package execution."""

        # Capture component configuration
        sql_server = self.sql_server
        sql_database = self.sql_database
        sql_username = self.sql_username
        sql_password = self.sql_password
        folder_name = self.folder_name
        project_name = self.project_name
        package_name = self.package_name
        asset_key = self.asset_key
        description = self.description
        group_name = self.group_name
        poll_interval_sec = self.poll_interval_sec
        max_wait_time_sec = self.max_wait_time_sec

        def execute_ssis_package(context: dg.AssetExecutionContext) -> dict:
            """Execute SSIS package via SSISDB catalog stored procedures."""

            connection_string = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={sql_server};"
                f"DATABASE={sql_database};"
                f"UID={sql_username};"
                f"PWD={sql_password};"
                f"Encrypt=yes;"
                f"TrustServerCertificate=no;"
            )

            context.log.info(
                f"Connecting to SSISDB: {sql_server}/{sql_database}"
            )

            conn = pyodbc.connect(connection_string)
            cursor = conn.cursor()

            try:
                # Step 1: Create execution
                context.log.info(
                    f"Creating execution for {folder_name}/{project_name}/{package_name}"
                )

                cursor.execute(
                    """
                    DECLARE @execution_id BIGINT
                    EXEC [SSISDB].[catalog].[create_execution]
                        @package_name = ?,
                        @execution_id = @execution_id OUTPUT,
                        @folder_name = ?,
                        @project_name = ?,
                        @use32bitruntime = False
                    SELECT @execution_id AS execution_id
                    """,
                    package_name,
                    folder_name,
                    project_name,
                )

                execution_id = cursor.fetchone()[0]
                context.log.info(f"Created execution ID: {execution_id}")

                # Step 2: Start execution
                context.log.info(f"Starting execution {execution_id}...")
                cursor.execute(
                    """
                    EXEC [SSISDB].[catalog].[start_execution] @execution_id = ?
                    """,
                    execution_id,
                )
                conn.commit()

                context.log.info(
                    f"✅ SSIS package execution started. Execution ID: {execution_id}"
                )

                # Step 3: Poll for completion
                return poll_for_completion(
                    context, conn, cursor, execution_id
                )

            except Exception as e:
                context.log.error(f"SSIS package execution failed: {str(e)}")
                raise
            finally:
                cursor.close()
                conn.close()

        def poll_for_completion(
            context: dg.AssetExecutionContext,
            conn: pyodbc.Connection,
            cursor: pyodbc.Cursor,
            execution_id: int,
        ) -> dict:
            """Poll SSISDB for execution status until completion."""

            start_time = time.time()
            elapsed_time = 0

            while elapsed_time < max_wait_time_sec:
                # Query execution status
                cursor.execute(
                    """
                    SELECT status,
                           CAST(start_time AS VARCHAR(50)) as start_time,
                           CAST(end_time AS VARCHAR(50)) as end_time
                    FROM [SSISDB].[catalog].[executions]
                    WHERE execution_id = ?
                    """,
                    execution_id,
                )

                row = cursor.fetchone()
                if not row:
                    raise Exception(
                        f"Execution ID {execution_id} not found in SSISDB catalog"
                    )

                status_code = row[0]
                start_time_db = row[1]
                end_time_db = row[2]

                try:
                    status = SSISExecutionStatus(status_code)
                except ValueError:
                    status_name = f"UNKNOWN({status_code})"
                else:
                    status_name = status.name

                context.log.info(
                    f"Execution {execution_id} status: {status_name} "
                    f"(elapsed: {elapsed_time:.1f}s)"
                )

                # Check if execution completed
                if status_code == SSISExecutionStatus.SUCCEEDED.value:
                    context.log.info(
                        f"✅ SSIS package execution succeeded! (ID: {execution_id})"
                    )

                    # Get execution statistics (row counts) from event messages
                    # Parse messages like: "OLE DB Destination" wrote 10 rows.
                    cursor.execute(
                        """
                        SELECT message
                        FROM [SSISDB].[catalog].[event_messages]
                        WHERE operation_id = ?
                        AND message LIKE '%wrote % rows%'
                        """,
                        execution_id,
                    )

                    # Parse row counts from messages
                    total_rows = 0
                    for row in cursor.fetchall():
                        message = row[0]
                        # Extract number from "wrote X rows" pattern
                        match = re.search(r'wrote (\d+) rows', message)
                        if match:
                            total_rows += int(match.group(1))

                    context.log.info(f"Total rows processed: {total_rows}")

                    return {
                        "execution_id": execution_id,
                        "status": status_name,
                        "total_rows_processed": total_rows,
                        "start_time": str(start_time_db) if start_time_db else None,
                        "end_time": str(end_time_db) if end_time_db else None,
                    }

                elif status_code == SSISExecutionStatus.FAILED.value:
                    # Get error details
                    cursor.execute(
                        """
                        SELECT TOP 1 message
                        FROM [SSISDB].[catalog].[operation_messages]
                        WHERE operation_id = ? AND message_type = 120
                        ORDER BY message_time DESC
                        """,
                        execution_id,
                    )
                    error_row = cursor.fetchone()
                    error_msg = error_row[0] if error_row else "Unknown error"

                    raise Exception(
                        f"SSIS package execution failed (ID: {execution_id}): {error_msg}"
                    )

                elif status_code in [
                    SSISExecutionStatus.CANCELED.value,
                    SSISExecutionStatus.ENDED_UNEXPECTEDLY.value,
                ]:
                    raise Exception(
                        f"SSIS package execution ended with status: {status_name} "
                        f"(ID: {execution_id})"
                    )

                # Still running, wait before next poll
                time.sleep(poll_interval_sec)
                elapsed_time = time.time() - start_time

            # Timeout reached
            raise Exception(
                f"SSIS package execution timed out after {max_wait_time_sec}s "
                f"(ID: {execution_id}). Current status: {status_name}"
            )

        @dg.asset(
            key=asset_key,
            description=description,
            group_name=group_name,
            kinds={"ssis", "azure"},
        )
        def ssis_package_execution(context: dg.AssetExecutionContext):
            """Execute SSIS package on Azure-SSIS Integration Runtime."""

            context.log.info(
                f"Executing SSIS package: {folder_name}/{project_name}/{package_name}"
            )

            result = execute_ssis_package(context)

            # Return execution metadata
            return dg.Output(
                value=result,
                metadata={
                    "execution_id": result["execution_id"],
                    "package_name": package_name,
                    "project_name": project_name,
                    "folder_name": folder_name,
                    "status": result["status"],
                    "total_rows_processed": result["total_rows_processed"],
                    "start_time": result.get("start_time", "N/A"),
                    "end_time": result.get("end_time", "N/A"),
                },
            )

        return dg.Definitions(assets=[ssis_package_execution])
