# Table of Content

- [Table of Content](#Table-of-Content)
- [Requirements](#Requirements)
- [Preparation Steps](#Preparation-Steps)
	- [Step #0.1 - Create a Volume](#Step-#0.1---Create-a-Volume)
	- [Step #0.2 - (Optionally) Enable OBO Authentication](#Step-#0.2---(Optionally)-Enable-OBO-Authentication)
- [Installation Steps](#Installation-Steps)
	- [Step #1 - Create Lakebase Instance](#Step-#1---Create-Lakebase-Instance)
	- [Step #2 - Create Ontos Database](#Step-#2---Create-Ontos-Database)
	- [Step #4 - Option A - Deploy the App via Marketplace](#Step-#4---Option-A---Deploy-the-App-via-Marketplace)
	- [Step #4 - Option B - Deploy the App via Git Repo](#Step-#4---Option-B---Deploy-the-App-via-Git-Repo)
	- [Step #5: (Optionally) Load Demo Data](#Step-#5:-(Optionally)-Load-Demo-Data)
	- [Troubleshooting](#Troubleshooting)
		- [Debugging Issues](#Debugging-Issues)
		- [Database Ownership](#Database-Ownership)
		- [Change of App Service Principle](#Change-of-App-Service-Principle)
		- [Role `admins` is Missing](#Role-`admins`-is-Missing)
		- [Unblock Remote Repositories](#Unblock-Remote-Repositories)
		- [Fix Access for Databricks Reader/Writer](#Fix-Access-for-Databricks-Reader/Writer)
	- [DANGER ZONE](#DANGER-ZONE)
	- [OBSOLETE: Step #6 - Lock Down the Database](#OBSOLETE:-Step-#6---Lock-Down-the-Database)

# Requirements

- A workspace where the following is given
	- You have Databricks Apps available and are allowed to deploy apps
	- You have Lakebase available and are allowed to create instances
	- You have a catalog you can use to set up a volume for the app
- Also see [Step #0.2 - (Optionally) Enable OBO Authentication](#Step-#0.2---(Optionally)-Enable-OBO-Authentication) 

Notes:
- If you want to map the Lakebase database of the app into a Unity Catalog catalog, you need `CREATE CATALOG` on the metastore. Mapping the database is not needed, strictly speaking, but allows to demo dashboards accessing the Ontos data directly.
# Preparation Steps

## Step #0.1 - Create a Volume

Ontos stores larger data that is accessible outside of the app in a volume. This includes:
- The images and documents attached as metadata to in-app objects
- The Git repo used for the *indirect deployment mode*

In the workspace, in the Lakehouse homepage, navigate to "Catalog" in the menu, then click on the "Create schema" button:

![](images/setup/bd04f07c678b323044172029d52c5da8.png)

Enter a name for the schema, and optionally specify a location etc.:

![](images/setup/7871a0d93dc530872d77ce2ea852c548.png)

Click "Create", which creates the schema and navigates the UI to its details page:

![](images/setup/9e3ad98c34eb4199e37805f7c22bbd0f.png)

Click on "Create" and select the "Volume" option:

![](images/setup/8e8dd4d588613c420d989515abe09082.png)

Enter a volume name, and optionally select other applicable options:

![](images/setup/1cb243c95c9aa98f6de3e9d75a3a6a02.png)

Click "Create", which creates the volume and navigates the UI to its details page:

![](images/setup/c1c96ba459d5be0562f1f4b835a66fff.png)

Note: The Databricks Apps service is automatically adding the Service Principle (SP) of the app to the volume (and schema, etc.), once the app is deployed:

![](images/setup/344aaf8851554eb5b2e755caabf83508.png)

![](images/setup/c37d29369080cc1c461a7a2bfc640d94.png)

## Step #0.2 - (Optionally) Enable OBO Authentication

Currently, the required [on-behalf-of users](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth#user-authorization) authentication is a Public Preview feature. If you try to set up the app _without_ enabling OBO for apps first, you may see this in [Step #4 - Option A - Deploy the App via Marketplace](#Step-#4---Option-A---Deploy-the-App-via-Marketplace):

![](images/setup/2285fc6c0141802e5cfc05db2e8d02ef.png)

For the time being, you have to enable this feature first by navigating to the "Previews" page using the user menu:

![](images/setup/76fa801b904eccf89d93b00477b0eb06.png)

Then toggle the following option to "On":

![](images/setup/218358545058a451c67c62414f198fd8.png)

# Installation Steps

## Step #1 - Create Lakebase Instance

Navigate to the "Lakebase Postgres" homepage:

![](images/setup/8a9e27b61ffbe80bdc7c9edf83bedd57.png)

Click in "Create Database Instance"

![](images/setup/1788547b3f204a15167e36b3ead5acb9.png)

Enter a name and press "Create":

![](images/setup/bfced6f03bb5aa4c6a996382bdc5d295.png)

Note: The capacity is not critical for demo setups, leave at default.

Wait for the instance to become available:

![](images/setup/df2e41fa2273707e17026c7f6584c514.png)

![](images/setup/783b05a8ce1c8680544e0d5779ad8f40.png)
## Step #2 - Create Ontos Database

Once the instance is available, click on the "Query" link in the *three-dot* menu:

![](images/setup/358e8b11e5934195bf7e1bb65326a761.png)

Then in the SQL editor, run these commands:

```sql
CREATE DATABASE app_ontos;
GRANT ALL ON DATABASE app_ontos TO PUBLIC;
```

![](images/setup/421b74c8ce6da58b0579ccb4d9fc4cb4.png)

The response should be "OK". In this step we created the database the app is using, and also granted access to that database to the `PUBLIC` role. This is required since we do not have the Service Principal (SP) of the app yet. The SP is created when the app is deployed, which requires for the database to already exist - a *chicken and egg* kind of problem.

## Step #4 - Option A - Deploy the App via Marketplace

In the Lakehouse homepage, click on "Marketplace" in the left-hand menu:

![](images/setup/e03761fba59950a3c3919f4a2b95d3bf.png)

Type in "ontos" in the *Search for products* edit in the middle of the screen:

![](images/setup/40759a07e836aed847ac4a622f4a896f.png)

Click on "Ontos" and see the details:

![](images/setup/4ba9deb18f013d1adf14ef8364b37375.png)

Note that the current version of the app is listed in the description, towards the end:

![](images/setup/f3f1aa83e917b14b792018b38501a7ff.png)

Then click on "Install" in the top-right corner of the listing:

![](images/setup/e5ee1b047b0ffe05f546ad7c8585b019.png)

Accept the agreement:

![](images/setup/9ecf7202987ceac687dca15680353a14.png)

Then on the "Install App" page, enter all pre-configured details:

![](images/setup/ac282f9f4a392d2d6f1bece992dc1f36.png)

Note: For testing, it is OK to leave the "Compute size" as the default value.

Click on "Next" and review the entered information, as well as the permission scopes the app is asking for:

![](images/setup/b3dbfdaa820bcacc78fe92237493429b.png)

Click "Next" again, enter a name for the app, and press "Install" to complete the wizard:

![](images/setup/da890d18b41c6c31c3a8d85f929384f1.png)

Now wait for the app to be deployed:

![](images/setup/8830f8a3cb21876e699230cf809ad6e1.png)

While waiting for the compute to start, click on "Permissions" and add any principal or group you want to allow access to the dedicated app endpoint:

![](images/setup/6c3fb9f7e5d4f612565bb0d71c8159eb.png)

Press "Add" and "Save" once done adding principals:

![](images/setup/9c6e8fd0178ceaa10f4458ca710c8462.png)

Once the container runtime is up the deployment is automatically initiated:

![](images/setup/1fe322b7f030417e091433f4af458c5c.png)

Wait again until the app is running:

![](images/setup/917749c4194c00a502fcf068fed11a69.png)

Then click on the app's URL to access the app:

![](images/setup/bea9b30360be3db20c4a89e00c5ab0c4.png)

Note: Every user access the app the first time are asked to accept the *on-behalf-of* permission scopes:

![](images/setup/2d81c8c08a6bbd5bb4908d8c082723ba.png)

Click "Authorize" and continue. The app's UI should now be visible:

![](images/setup/d2b04bb5086c177da39d4b4785aa2c02.png)

Note: The app's URL is the name of the app (specified earlier) and the workspace ID, plus the cloud name, and a fixed TLD set to `databricksapps.com`.

## Step #4 - Option B - Deploy the App via Git Repo

Start by first copying the HTTPS URL:

![](images/setup/aa5eb4b7fb76aede65066f67d7b39ee9.png)

Then go to a Workspace folder, like `Shared`, and clone the repo using a "Git folder":

![](images/setup/3d1137c870f938df0f73c6cb65213915.png)

Paste the URL, modify the name as needed (here adding `-git` as a postfix) and press "Create Git folder":

![](images/setup/c285f5b9cc2364e4aff6e8955f618cb0.png)

Wait a little while:

![](images/setup/5052efbef28be7d4c168ba3e88fa208c.png)

There it is, the UI loads the newly create folder:

![](images/setup/65fa18fb4efff4964baf90bf903c0946.png)

Navigate to "Compute", then click on the "Apps" tab, then click on "Create app":

![](images/setup/d2b61db05d5b1e387c64b121c5a75335.png)

Select "Crate a custom app" (first entry):

![](images/setup/09e1c02460c628c752aead36082ef0f4.png)

Then enter a name, like `ontos-dev` and press "Next: Configure":

![](images/setup/a9fcf9259339343a22650429eee92e70.png)

On this page, we have to configure the *resources* and *scopes* manually:

![](images/setup/b4b0b36b79a2a1ec93aea199c1cf90f6.png)

In the end, this should look something like this:

![](images/setup/5a901151724b1e224983e5d1b36c806a.png)

You can look at the [manifest.yaml](https://github.com/databrickslabs/ontos/blob/main/src/manifest.yaml) file in the repo for the resources and scopes you have to pick.

Notes: 
- For testing and light work, leave the instance size as its default value (i.e. "Medium").
- Leave all the "Resource key" values default, they have to match what is specified in the [app.yaml](https://github.com/databrickslabs/ontos/blob/main/src/app.yaml) file in the repo - which uses the defaults (see `valueFrom` lines). 
- Also leave the "Permissions" default BUT for the volume, were you need to pick "Can read and write" (see below).
  ![](images/setup/a129bfd2570e4cab0b3ec34314518b72.png)

Then click on "Create app":

![](images/setup/49ea584a8bfe5375f0b8cdc1faf952fa.png)

The Apps service is then spinning up the container runtime:

![](images/setup/c3e16a47fd8a2a4d8d318c54c398850d.png)

Once the container runtime is up and running, press the "Deploy" button to start the app deployment:

![](images/setup/b195eeb25cf1ff4d64e7f78531e21d2f.png)

This will open a dialog the first time you press "Deploy", asking you to supply the source path. Set it to the path where you cloned the repo into, while adding `/src` at the end. This is IMPORTANT!

![](images/setup/7185000932e55752dcec6d1df7149ffb.png)

Now wait for the app to be deployed:

![](images/setup/f482e05b7eb5e72e3ec50904005393fc.png)

While waiting, click on "Permissions" and add any principle to the list of users who can manage or access the app. 

Note: You need `CAN_MANAGE` to access the current page. Users with `CAN_USE` can _only_ access the app URL, not the Databricks Apps page.

![](images/setup/87fedf6fecd0e8f7a932ecb07ac5aaf8.png)

Once the app is up, click on the app's URL to open it.

![](images/setup/7273b9f468b70332c761c8b21bc839c6.png)

![](images/setup/fc72d2df1d292be749dc1b6057109801.png)

![](images/setup/360b95c5db50b21c39afbbfd7f3504d8.png)

## Step #5: (Optionally) Load Demo Data

Ontos ships with five **standalone demo packs** — one per industry — and the
`POST /api/settings/demo-data/load` endpoint accepts a `preset` query
parameter to pick exactly one of them:

| `preset`  | File                       | Vertical flavour                                |
| --------- | -------------------------- | ----------------------------------------------- |
| `retail`  | `demo_data_retail.sql`     | Retail / e‑commerce (default)                   |
| `hls`     | `demo_data_hls.sql`        | Healthcare & Life Sciences (clinical, claims)   |
| `fsi`     | `demo_data_fsi.sql`        | Financial Services (banking, capital markets)   |
| `mfg`     | `demo_data_mfg.sql`        | Manufacturing (production, quality, EHS)        |
| `auto`    | `demo_data_auto.sql`       | Automotive (connected vehicle, ADAS, warranty)  |

Each preset is fully self‑contained: it brings its own data domains, business
roles, delivery methods, ontology concepts, vertical asset types, tag
namespaces, workflows, assets, lineage, owners, comments, compliance runs and
cost items. You can load any preset on top of an empty database without
needing the retail base.

Navigate to the `/docs` page in Ontos (by editing the URL in the browser's
address bar) to use them interactively:

![](images/setup/eab238b2452e97910df4a5f3058e9717.png)

Search for "demo":

![](images/setup/ea898dadcd3936d9431ce6b8a92eccf9.png)

The two endpoints available are to load and, later, unload the demo data.

`POST /api/settings/demo-data/load` accepts a single `preset` query parameter
(`retail` | `hls` | `fsi` | `mfg` | `auto`, default `retail`). The matching
`demo_data_{preset}.sql` is the only file executed — there is no implicit
"base + overlay" layering, so each preset is loaded standalone.

Note: All demo data uses very specific codes in its UUIDs (a per‑preset
segment such as `0000`, `0001`, `0002`, …) so that we can discern demo
records from data entered manually by users, and so that `DELETE demo-data`
can clean up exactly what was inserted.

Open the `POST load` endpoint and click on "Try it out":

![](images/setup/a614e01cb5b297ce4c1a4eae473dfc7b.png)

Then click on "Execute" to trigger the endpoint:

![](images/setup/633c27505291c410331e1e97c67e0d53.png)

The page spins briefly, then confirms the call:

![](images/setup/2a0ce04fc0ca598423616af995b6a1b7.png)

Reload the app, it now has demo data:

![](images/setup/f2d90a46da4aa95addcceceb2931a4d2.png)

Note: Each preset is delivered as a standalone SQL file under
`src/backend/src/data/demo_data_{preset}.sql` and can be edited or extended
to reflect other industries or individual customers without affecting the
other packs.

Use the `DELETE demo-data` endpoint shown above to clear all demo records
across every preset (it deletes by demo UUID prefix, so any combination of
loaded packs is removed).

## Troubleshooting

### Debugging Issues

A note here, the Databricks Apps UI is different when deploying apps from the marketplace, versus from a workspace folder. It is missing essential tabs, like "Logs" and "Environment". You can cheat here (for now at least) and click on say "Insights":

![](images/setup/6379aa5e9d5d907a4f16613f72f64875.png)

Then manually edit the URL in the address bar and replace the last part `insights` with `logs` or `environment` to access these helpful pages:

![](images/setup/1025de48a4114e486d80a098eaacbc7f.png)

![](images/setup/19d973d9ab4af87874c4fedd1502660e.png)

Note: The logs page is access the container proxy and requires that the permission scopes have been accepted first. When you debug a failed installation, the earlier step of accepting the scopes may not be possible. In that case the page may be empty and not show any logs. To solve this, click on the link in the "You can also click [here](here) to view the logs in a new tab." message and then accept the permission scopes in the page that opens. Once accepted, you will see the logs in the "Logs" tab as well as in the separate page.

### Database Ownership

It is important to note that the schema inside the configured database is created and maintained by the SP of the application. You can see this by running this query:

```sql
SELECT nspname AS schema_name,
       pg_get_userbyid(nspowner) AS owner
FROM pg_namespace
ORDER BY nspname;
```

For example (note that you MUST select the proper database in the SQL editor first):

![](images/setup/bb5e1b322fa4cb4122fa8210fd76e0b7.png)

The `app_ontos` schema (which is the default configured in [app.yaml](https://github.com/databrickslabs/ontos/blob/48167bd2ddb2a9f56971f67bd1ec0e7aa9d275bc/src/app.yaml#L24)) is owned by the UUID representing the apps Service Principal. Since you have NOT been granted access, you CANNOT access this database, even when you map the database into Unity Catalog. For example:

![](images/setup/492a8b891258860386dd12f12564d7e0.png)

![](images/setup/9a7d5793f9c7c5d5b5d893f31e664fc1.png)

![](images/setup/d19d591ed672f9ae16201cb21e4d7725.png)

You MUST grant your role, which equals your workspace ID (aka, your email address), explicit access.

```sql
-- Grant USAGE permission (required to access objects in the schema)
GRANT USAGE ON SCHEMA app_ontos TO "your_user@email.com";

-- Grant CREATE permission (allows creating new tables/objects)
GRANT CREATE ON SCHEMA app_ontos TO "your_user@email.com";

-- Grant read/write access to all existing tables
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app_ontos TO "your_user@email.com";

-- Grant permissions on future tables (so you automatically get access to new tables)
ALTER DEFAULT PRIVILEGES IN SCHEMA app_ontos 
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "your_user@email.com";

-- Grant permission to use sequences (needed for auto-incrementing columns)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app_ontos TO "your_user@email.com";

-- Grant permissions on future sequences
ALTER DEFAULT PRIVILEGES IN SCHEMA app_ontos 
GRANT USAGE, SELECT ON SEQUENCES TO "your_user@email.com";
```

### Change of App Service Principle

If you replace the app instance completely, but want to use the previous database, you have to connect to Postgres and grant access to the database to the new Service Principal.

### Role `admins` is Missing

After installing the app and access the UI, you may be confronted with this screen:

![](images/setup/db00c2c2e7e8ed95fbe53e7c4c018c99.png)

This is OK for subsequent users, but not for the initial setup and first admin. In that case - for now - you have to modify the database to set a suitable role, like so:

```sql
-- This assumes you are connected to the app's database. Use \c <db_name> if not.
-- Then set the search path to the configured schema, default is `app_ontos`
-- (set in the `app.yaml`).
app_ontos=> SET search_path TO app_ontos;

-- Get the UUID of the `Admin` app role
app_ontos=> select id, name, assigned_groups from app_roles where name='Admin';
                  id                  | name  | assigned_groups 
--------------------------------------+-------+-----------------
 f8a3a916-24b4-46ec-82b8-4530c8934c96 | Admin | ["admins"]
(1 row)

-- Set appropriate groups. `users` means everyone in the workspace and might 
-- be too broad. Consider setting it to a dedicated admin group instead.
app_ontos=> update app_roles set assigned_groups = '["admins","users","dbx_ontos_admins"]' where id = 'f8a3a916-24b4-46ec-82b8-4530c8934c96';
UPDATE 1

-- Verify the change
app_ontos=> select id, name, assigned_groups from app_roles where name='Admin';
                  id                  | name  |            assigned_groups            
--------------------------------------+-------+---------------------------------------
 f8a3a916-24b4-46ec-82b8-4530c8934c96 | Admin | ["admins","users","dbx_ontos_admins"]
(1 row)
```

After that, reload the UI, it should start to work!

### Unblock Remote Repositories

Depending on the setup, accessing required external repositories during the Databricks Apps deployment process may fail. This often shows in the logs as the deployment being stuck, and eventually a timeout error is shown. You MUST ensure the following FQDNs are NOT blocked:

```
registry.yarnpkg.com
registry.npmjs.org
pypi.org
pypi.python.org
```

In the Databricks Account console, configure the above hostnames in the network's *egress* rules. For example:

![](images/setup/eb2cc523f87a7e5385168bfa3db1abe9.png)

Once these hostnames are added, the deployment of the app should be able to proceed as expected.

### Solve Scope Change Issues

Databricks Apps uses a [Scope-based Security](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth#scope-based-security-and-privilege-escalation) model. When deploying the app from the Marketplace, these are defined in the [Manifest YAML](https://github.com/databrickslabs/ontos/blob/main/src/manifest.yaml) file and cannot be changed currently without recreating the app's marketplace listing. But for installations using the source code, you need to configure the scopes manually in the Apps UI during the Custom App installation process (explained above). 

When you modify these scopes later on, they are NOT automatically available to the app! Recall that each user has to accept the current scopes once when the app is opened first. That information is stored in the browser cookie storage and reused from there. You may see an error like the following in the app or its logs:

```
ERROR - Error fetching catalogs.list: Provided OAuth token does not have required scopes: unity-catalog
```

This can be caused by a later change of scopes with the cookie missing the update. The fix is to remove the cookie for the app's URL in the browser and reloaded that page. It MUST then ask the user again to accept the current scopes, now with the latest ones present. After that, the error should go away.

### Fix Access for Databricks Reader/Writer

The Databricks control plane uses a dedicated set of roles to read and write data, as well as access the information schema. If you run into [DANGER ZONE](#DANGER-ZONE), you can fix access like so:

```sql
➜ psql "host=instance-025df497-74e6-461a-bfed-f2313585b527.database.azuredatabricks.net user=lars.george@databricks.com dbname=databricks_postgres port=5432 sslmode=require"
Password for user lars.george@databricks.com: 
psql (16.11 (Homebrew))
SSL connection (protocol: TLSv1.3, cipher: TLS_AES_256_GCM_SHA384, compression: off)
Type "help" for help.

databricks_postgres=> \c app_ontos_dev
SSL connection (protocol: TLSv1.3, cipher: TLS_AES_256_GCM_SHA384, compression: off)
You are now connected to database "app_ontos_dev" as user "lars.george@databricks.com".

-- Check which roles cannot connect to the database
app_ontos_dev=> SELECT rolname, has_database_privilege(rolname, 'app_ontos_dev', 'CONNECT') AS can_connect FROM pg_roles WHERE rolcanlogin;
               rolname                | can_connect 
--------------------------------------+-------------
 cloud_admin                          | t
 databricks_control_plane             | t
 databricks_monitor                   | f
 databricks_gateway                   | f
 databricks_replicator                | f
 lars.george@databricks.com           | t
 databricks_writer_16490              | f
 databricks_reader_16490              | f
 databricks_writer_16493              | f
 databricks_reader_16493              | f
 aa8b01e6-ea8f-4426-be12-25f2cd23197f | f
 databricks_writer_17918              | f
 databricks_reader_17918              | f
 4e81a6a0-eaf7-4899-81a6-27462b99b4b3 | t
(14 rows)

-- Grant CONNECT again
app_ontos_dev=> GRANT CONNECT ON DATABASE app_ontos_dev
TO databricks_writer_17918,
   databricks_reader_17918,
   "aa8b01e6-ea8f-4426-be12-25f2cd23197f";
GRANT

-- Grant USAGE again
app_ontos_dev=> GRANT USAGE ON SCHEMA app_ontos TO databricks_writer_17918, databricks_reader_17918;
GRANT SELECT, INSERT, UPDATE, DELETE
ON ALL TABLES IN SCHEMA app_ontos
TO databricks_writer_17918;
GRANT SELECT
ON ALL TABLES IN SCHEMA app_ontos
TO databricks_reader_17918;
GRANT
GRANT
GRANT
app_ontos_dev=> 
```

## DANGER ZONE

The following step was meant to proactively limit the access to the app's database for just the app's Service Principal. The issue is that the `REVOKE` command is also removing the access for the control plane. When you map the Postgres database into UC, it will tell you that it cannot access it:

![](images/setup/a7d1b9dbed6fe33108e665f19e4b7125.png)

See [Fix Access for Databricks Reader/Writer](#Fix-Access-for-Databricks-Reader/Writer) how to fix this.
## OBSOLETE: Step #6 - Lock Down the Database

Click on the app's "Overview" tab, then copy the Service Principal using the "Copy" button:

![](images/setup/fad42cb290f0ff8c84c8069a29c1c2fa.png)

Note: We need the SPs UUID, not the readable name shown in the UI. The "Copy" button copies the UUID we need. 

Go to the SQL Editor from earlier (also available under "SQL Editor" in the Lakehouse homepage) and enter the following, while pasting the copied UUID into place:

```sql
GRANT ALL ON DATABASE app_ontos TO "<paste_copied_SP_UUID_here";
REVOKE ALL ON DATABASE app_ontos FROM PUBLIC;
```

For example:

![](images/setup/b4cfda45c602b572ee8076d8dcd19e4c.png)

Run those new two lines, which will close the broader access to the database and limit it to the app's Postgres role. 

Note: The Postgres role is created by the integration between Databricks Apps and Lakebase. Once you deploy an app, the Apps service creates an SP and adds it to the Lakebase Postgres instance, also visible in the "Roles" menu:

![](images/setup/bf2bc8f0ff6892e862f691af949df0e4.png)
