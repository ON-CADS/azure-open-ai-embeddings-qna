import requests
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv
from openai import AzureOpenAI
import re
import json

load_dotenv()

# Constants for Salesforce credentials and login URL


AZURE_ENDPOINT = os.environ.get('AZURE_ENDPOINT') 
OPEN_AI_KEY = os.environ.get('OPEN_AI_KEY') 
OPENAI_RESOURCE_VERSION = os.environ.get('OPENAI_RESOURCE_VERSION') 
OPENAI_RESOURCE_MODEL= os.environ.get('OPENAI_RESOURCE_MODEL') 
LOGIN_URL= os.environ.get('LOGIN_URL')
SF_USERNAME = os.environ.get('SF_USERNAME') 
SF_PASSWORD = os.environ.get('SF_PASSWORD') 
CLIENT_ID= os.environ.get('CLIENT_ID') 
CLIENT_SECRET=os.environ.get('CLIENT_SECRET') 

client = AzureOpenAI(
    azure_endpoint = AZURE_ENDPOINT,
    api_key = OPEN_AI_KEY,  
    api_version = OPENAI_RESOURCE_VERSION
) 

def authenticate_salesforce():
    """Authenticate with Salesforce and return access token and instance URL."""
    payload = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": SF_USERNAME,
        "password": SF_PASSWORD
    }

    response = requests.post(f"{LOGIN_URL}/services/oauth2/token", data=payload, verify=False)
    if response.status_code != 200:
        raise ConnectionError(f"Authentication failed: {response.status_code} - {response.text}")

    auth_response = response.json()
    return auth_response["access_token"], auth_response["instance_url"]


SYS_PROMPT_OPTY_COMMENTS_SUMMARY='''

Given input text, write the summary

Instructions:
1. Use only the content provided in the input text.
2. Summarize only the most recent comments based on the latest date.
3. Begin the summary with: "As of *date*"
4. Return the result in JSON format with the key "Summary".
5. If no comments are available or the comments are incomplete, return:
   {"Summary": "No Sales Comments available on this opportunity"}

Input Text:
'''
def get_opty_comments_summary(comments):
    # Step 8: Initialize the language model client (e.g., GPT-4o)
    #chat_model_client = get_llm("gpt-4o-2024-08-06", temperature=0.0)

    # Step 9: Prepare messages for the model with system prompt and user input
    completion = client.chat.completions.create(
                model=OPENAI_RESOURCE_MODEL, # Or gpt-4o depending on your plan
                messages=[
                    {"role": "system", "content": SYS_PROMPT_OPTY_COMMENTS_SUMMARY},
                    {"role": "user", "content": comments}
                ],
                temperature=0.2
            )



    #print(ai_msg.content)

    
    try:
        # Try parsing the entire response directly
        return json.loads(completion.choices[0].message.content)

    except json.JSONDecodeError:
        # Step 11: Try to extract JSON content from the model's response using regex
        json_match = re.search(r'```json\\n(.*?)```', completion.choices[0].message.content, re.DOTALL) or \
                    re.search(r'```json\n(.*?)```', completion.choices[0].message.content, re.DOTALL)

        print('json_match',json_match)
        # Step 12: If JSON is found, attempt to parse it
        if json_match:
            try:
                json_obj = json.loads(json_match.group(1))
                #print(json_obj)  # Optional: print for debugging
                return json_obj
            except json.JSONDecodeError as e:
                print(f"JSON decoding failed: {e}")
                return None
        else:
            # Step 13: If no JSON block is found in the response
            print("No JSON found in the model response.")
            return None

#result_df['Sales_Comments_summary']=result_df['Sales_Comments'].apply(lambda x: get_opty_comments_summary(str(x)))
#result_df

def extract_summary(comment):
    summary_dict = get_opty_comments_summary(str(comment))
    return summary_dict.get("Summary") if summary_dict else None

def build_query(corp_code):
    """Construct the SOQL query for fetching opportunities."""
    #today = pd.to_datetime(datetime.today().date())
    current_date = datetime.today().strftime('%Y-%m-%d')
    query = (
        f'''
SELECT 
    Id,
    Opportunity_Number__c,
    Name,
    Estimated_Board_Annual_Revenue_USD2__c,
    Must_Win__c, 
    Market_Segment__c,
    Application__c,
    Start_of_Production_Date__c,
    Opty_Comments__c,
    Number_of_Sockets__c
FROM Opportunity WHERE (Account.Parent.AccountNumber='{corp_code}' OR End_Customer__r.AccountNumber  ='{corp_code}') AND StageName = 'Active' AND Start_of_Production_Date__c >= THIS_YEAR
ORDER BY Must_Win__c DESC, Estimated_Board_Annual_Revenue_USD2__c DESC Limit 5 
'''
    )
    return query

def fetch_data(instance_url, access_token, query):
    """Fetch data from Salesforce using the constructed query and return a normalized DataFrame."""
    headers = {"Authorization": f"Bearer {access_token}"}
    query_url = f"{instance_url}/services/data/v60.0/query?q={query}"
    response = requests.get(query_url, headers=headers, verify=False)


    try:
        print("********ksnccdk cdc")
        data = response.json()
        records = data.get("records", [])
        df = pd.DataFrame(records)

        # Expand nested dictionaries
        if 'Opportunity_Name__r' in df.columns:
            df_Opportunity_Name__r = df['Opportunity_Name__r'].apply(pd.Series).add_prefix('Opportunity_Name__r')
            df = df.drop(columns='Opportunity_Name__r').join(df_Opportunity_Name__r)

        # Expand nested dictionaries
        if 'Opportunity_Name__r' in df.columns:
            df_Opportunity_Name__r = df['Opportunity_Name__r'].apply(pd.Series).add_prefix('Opportunity_Name__r')
            df = df.drop(columns='Opportunity_Name__r').join(df_Opportunity_Name__r)

        if 'Opportunity_Name__rAccount' in df.columns:
            df_Opportunity_Name__r = df['Opportunity_Name__rAccount'].apply(pd.Series).add_prefix('Opportunity_Name__rAccount')
            df = df.drop(columns='Opportunity_Name__rAccount').join(df_Opportunity_Name__r)

        if 'Opportunity_Name__rAccountParent' in df.columns:
            df_Opportunity_Name__r = df['Opportunity_Name__rAccountParent'].apply(pd.Series).add_prefix('Opportunity_Name__rAccountParent')
            df = df.drop(columns='Opportunity_Name__rAccountParent').join(df_Opportunity_Name__r)

        if 'Opportunity_Name__rAccountParentGlobal_Account_Manager__r' in df.columns:
            df_Opportunity_Name__r = df['Opportunity_Name__rAccountParentGlobal_Account_Manager__r'].apply(pd.Series).add_prefix('Opportunity_Name__rAccountParentGlobal_Account_Manager__r')
            df = df.drop(columns='Opportunity_Name__rAccountParentGlobal_Account_Manager__r').join(df_Opportunity_Name__r)

        return df

    except ValueError:
        raise ValueError(f"Failed to parse JSON response: {response.text}")

def process_data(records):
    """Process the raw records into a formatted DataFrame."""
    column_mapping = {
        'Opportunity_Number__c': 'Opportunity Number',
        'Name': 'Opportunity Name',
        'Must_Win__c': 'Must Win',
        'Estimated_Board_Annual_Revenue_USD2__c': 'Estimated Annual Revenue',
        'Number_of_Sockets__c': 'Number of Sockets',
        'Start_of_Production_Date__c': 'Production Date',
        'Market_Segment__c': 'Market Segment',
        'Sub_Application__c': 'Application',
        'GAM_From_Parent_Account__c': 'GAM',
        'Opty_Comments__c': 'Comments'
    }

    selected_columns = list(column_mapping.keys())
    df = pd.json_normalize(records)
    df = df[selected_columns]
    df.rename(columns=column_mapping, inplace=True)
    return df

def aggregate_rows(group):
        first_row = group.iloc[0].copy()
        first_row['Sales_Comment__c'] = ' '.join(filter(None, group['Sales_Comment__c']))
        first_row['SBQQ__ProductName__c'] = ','.join(filter(None, group['SBQQ__ProductName__c']))
        first_row['Sales_Socket_Statuses__c'] = ','.join(filter(None, group['Sales_Socket_Statuses__c']))
        first_row['Must_WIN__c'] = group['Must_WIN__c'].any()
        return first_row

def fetch_opportunities(corp_code,limit=5):
    """Main function to fetch and process Salesforce opportunities."""
    try:
        access_token, instance_url = authenticate_salesforce()
        current_date = datetime.today().strftime('%Y-%m-%d')
        query = build_query(corp_code)
        records = fetch_data(instance_url, access_token, query)
        print('****************************records',records)
        return records #process_data(records)
    except Exception as e:
        print(f"Error: {e}")
        return pd.DataFrame()

def aggregate_rows(group):
    first_row = group.iloc[0].copy()
    first_row['Sales_Comment__c'] = ' '.join(filter(None, group['Sales_Comment__c']))
    first_row['SBQQ__ProductName__c'] = ','.join(filter(None, group['SBQQ__ProductName__c']))
    first_row['Sales_Socket_Statuses__c'] = ','.join(filter(None, group['Sales_Socket_Statuses__c']))
    first_row['Must_WIN__c'] = group['Must_WIN__c'].any()
    return first_row

def get_funnel_for_customer(corp_code):

    corp_code =corp_code["code"]
    #corp_code = corp_code
    # Call the function
    result_df = fetch_opportunities(corp_code=corp_code)
    print('****************result_df',result_df)
    
    opportunity_numbers = result_df['Opportunity_Number__c'].values.tolist()
    print(opportunity_numbers)

    access_token, instance_url = authenticate_salesforce()
    in_clause = ','.join(f"'{num}'" for num in opportunity_numbers)
    query = (f'''
SELECT
    Opportunity_Name__r.Opportunity_Number__c,
    Opportunity_Name__r.Name,
    Opportunity_Name__r.Start_of_Production_Date__c,
    Opportunity_Name__r.Number_of_Sockets__c,
    Opportunity_Name__r.Market_Segment__c,
    Opportunity_Name__r.Application__c,
    SBQQ__ProductName__c,
    SBQQ__Product__r.Name,
    Must_WIN__c,
    Opportunity_Name__r.Estimated_Board_Annual_Revenue_USD2__c,
    Opportunity_Name__r.Account.Parent.Global_Account_Manager__r.Name,
    Sales_Socket_Statuses__c,
    Sales_Comment__c
FROM SBQQ__QuoteLine__c
WHERE Opportunity_Name__r.Opportunity_Number__c IN ({in_clause})
    AND Primary__c = TRUE
    AND (NOT Sales_Socket_Statuses__c LIKE 'Lost%')
    AND (NOT Sales_Socket_Statuses__c LIKE 'Cancelled%')
ORDER BY Opportunity_Name__r.Opportunity_Number__c, Must_WIN__c DESC, Estimated_Board_Annual_Revenue_USD2__c DESC
    '''
)


    result_df = fetch_data(instance_url, access_token, query)

    sel_columns=['Opportunity_Name__rOpportunity_Number__c','Opportunity_Name__rName','Opportunity_Name__rEstimated_Board_Annual_Revenue_USD2__c','Must_WIN__c','Opportunity_Name__rMarket_Segment__c','Opportunity_Name__rApplication__c','Opportunity_Name__rStart_of_Production_Date__c','Opportunity_Name__rAccountParentGlobal_Account_Manager__rName','Sales_Comment__c','Opportunity_Name__rNumber_of_Sockets__c','SBQQ__ProductName__c','Sales_Socket_Statuses__c']
    df_sorted=result_df[sel_columns]

    result_df = df_sorted.groupby('Opportunity_Name__rOpportunity_Number__c', group_keys=False).apply(aggregate_rows).reset_index(drop=True)

    # Convert the column to datetime
    result_df['Opportunity_Name__rStart_of_Production_Date__c'] = pd.to_datetime(result_df['Opportunity_Name__rStart_of_Production_Date__c'], errors='coerce')

    today = pd.to_datetime(datetime.today().date())
    result_df = result_df[result_df['Opportunity_Name__rStart_of_Production_Date__c'] > today]
    result_df=result_df.sort_values(by=['Must_WIN__c', 'Opportunity_Name__rEstimated_Board_Annual_Revenue_USD2__c'], ascending=[False, False])[:5]
    #result_df.to_csv("sample3.csv")


    # Rename columns with meaningful names
    result_df.rename(columns={
        'Opportunity_Name__rOpportunity_Number__c': 'Opportunity_Number',
        'Opportunity_Name__rName': 'Opportunity_Name',
        'Opportunity_Name__rEstimated_Board_Annual_Revenue_USD2__c': 'Estimated_Annual_Revenue_USD',
        'Must_WIN__c': 'Must_Win',
        'Opportunity_Name__rMarket_Segment__c': 'Market_Segment',
        'Opportunity_Name__rApplication__c': 'Application',
        'Opportunity_Name__rStart_of_Production_Date__c': 'Start_of_Production_Date',
        'Opportunity_Name__rAccountParentGlobal_Account_Manager__rName': 'GAM',
        'Sales_Comment__c': 'Sales_Comments',
        'Opportunity_Name__rNumber_of_Sockets__c': 'Number_of_Sockets',
        'SBQQ__ProductName__c':'Top_3_Sockets',
        'Sales_Socket_Statuses__c':'Socket_Status'
    }, inplace=True)


    
    result_df['Sales_Comments'] = result_df['Sales_Comments'].apply(extract_summary)

    result_df["Start_of_Production_Date"] = result_df["Start_of_Production_Date"].astype(str)
    result_df["Number_of_Sockets"] = result_df["Number_of_Sockets"].astype(int)

    result_df['Estimated_Annual_Revenue_USD'] = result_df['Estimated_Annual_Revenue_USD'].apply(lambda x: f"${x:,.0f}")


    #result_df.to_csv("chec.csv")
    access_token, instance_url = authenticate_salesforce()
    query = (f'''
    SELECT
        Opportunity_Name__r.Opportunity_Number__c,
        Opportunity_Name__r.Must_WIN__c,
        Opportunity_Name__r.Estimated_Board_Annual_Revenue_USD2__c,
        SBQQ__ProductName__c,
        Sales_Socket_Statuses__c,
        SBQQ__Product__r.Name
    FROM SBQQ__QuoteLine__c
    WHERE Opportunity_Name__r.Opportunity_Number__c in ({','.join(f"'{num}'" for num in opportunity_numbers)})
    AND Primary__c = TRUE
    ORDER BY Estimated_Board_Annual_Revenue_USD2__c DESC, Must_WIN__c DESC
    ''')

    records = fetch_data(instance_url, access_token, query)
    cols = [
    'Opportunity_Name__rOpportunity_Number__c',
    'Opportunity_Name__rMust_Win__c',
    'Opportunity_Name__rEstimated_Board_Annual_Revenue_USD2__c',
    'SBQQ__ProductName__c',
    'Sales_Socket_Statuses__c'
]
    records=records[cols]

    # Sort by Opportunity Number, Must Win (True first), and Estimated Revenue descending

    records_sorted = records.sort_values(
    by=['Opportunity_Name__rOpportunity_Number__c', 'Opportunity_Name__rMust_Win__c', 'Opportunity_Name__rEstimated_Board_Annual_Revenue_USD2__c'],
    ascending=[True, False, False]
)
 
    # Group by Opportunity Number and take top 3 rows per group
    top_3_per_opportunity = records_sorted.groupby('Opportunity_Name__rOpportunity_Number__c').head(3)
    
    top_3_per_opportunity
   
    df2_renamed = top_3_per_opportunity.rename(columns={
        'Opportunity_Name__rOpportunity_Number__c': 'Opportunity_Number',
        'Opportunity_Name__rMust_Win__c': 'Must_Win',
        'Opportunity_Name__rEstimated_Board_Annual_Revenue_USD2__c': 'Estimated_Annual_Revenue_USD'
    })
    df2_renamed['Estimated_Annual_Revenue_USD'] = df2_renamed['Estimated_Annual_Revenue_USD'].apply(lambda x: f"${x:,.0f}")
    #df2_renamed.to_csv("check.csv")
    merged_df = pd.merge(result_df, df2_renamed, on=['Opportunity_Number', 'Must_Win', 'Estimated_Annual_Revenue_USD'], how='inner')
    merged_df.drop(columns=['Top_3_Sockets','Socket_Status'], inplace=True)

    merged_df.rename(columns={'Opportunity_Number': 'Opportunity Number', 
                            'Opportunity_Name': 'Opportunity Name',
                            'Estimated_Annual_Revenue_USD': 'Estimated Annual Revenue USD',
                            'Must_Win': 'Must Win',
                            'Market_Segment': 'Market Segment',
                            'Start_of_Production_Date': 'Start of Production Date',
                            'Sales_Comments': 'Sales Comments',
                            'Number_of_Sockets': 'Number of Sockets',
                            'SBQQ__ProductName__c' : 'Top 3 Sockets',
                            'Sales_Socket_Statuses__c':'Socket Status'
                            }, inplace=True)


    merged_df['Top 3 sockets | Status'] = merged_df['Top 3 Sockets'] + '|' + merged_df['Socket Status']
    merged_df.drop(columns=['Top 3 Sockets','Socket Status'], inplace=True)

    #merged_df.to_csv("sample3.csv")

    group_columns = [
        'Opportunity Number', 'Opportunity Name', 'Estimated Annual Revenue USD', 'Must Win',
        'Market Segment', 'Application', 'Start of Production Date', 'GAM', 'Sales Comments','Number of Sockets'
    ]

    # Aggregate the remaining columns
    aggregated_df = merged_df.groupby(group_columns).agg({
        'Top 3 sockets | Status': lambda x: '\n'.join(x),
    }).reset_index()

    # Step 1: Clean the 'Estimated Annual Revenue USD' column (remove $, commas and convert to float)
    aggregated_df['Estimated Annual Revenue USD'] = aggregated_df['Estimated Annual Revenue USD'].replace('[\$,]', '', regex=True).astype(float)
    
    # Step 2: Sort by 'Estimated Annual Revenue USD' in descending order
    aggregated_df.sort_values(by='Estimated Annual Revenue USD', ascending=False, inplace=True)

    # Step 3: Format back to currency style
    aggregated_df['Estimated Annual Revenue USD'] = aggregated_df['Estimated Annual Revenue USD'].apply(lambda x: f"${x:,.0f}")
    
    #aggregated_df.to_csv("sample4.csv")

    json_output = aggregated_df.to_json(orient="records", indent=2)
    json_output = json.loads(json_output)
    print('json_output',json_output)
    return json_output

#print(get_funnel_for_customer('CTIC'))
